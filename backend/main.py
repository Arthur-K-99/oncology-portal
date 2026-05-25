import os
import re
import json
import logging
import tempfile
import asyncio
import subprocess
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("oncology-portal")

app = FastAPI(
    title="Oncology Variant & Drug Repurposing Portal API",
    description="Backend API mapping genetic variants and genes to therapeutic insights via SSE streaming.",
    version="2.0.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helper function to run the CLI wrappers safely
def run_cli_tool(tool_name: str, subcommand: str, extra_args: list[str]) -> Optional[Any]:
    script_paths = {
        "dbsnp": "/Users/athanasios/.gemini/config/plugins/science/skills/dbsnp_database/scripts/dbsnp_cli.py",
        "clinvar": "/Users/athanasios/.gemini/config/plugins/science/skills/clinvar_database/scripts/clinvar_api.py",
        "gtex": "/Users/athanasios/.gemini/config/plugins/science/skills/gtex_database/scripts/gtex_cli.py",
        "opentargets": "/Users/athanasios/.gemini/config/plugins/science/skills/opentargets_database/scripts/query_opentargets.py",
        "chembl": "/Users/athanasios/.gemini/config/plugins/science/skills/chembl_database/scripts/chembl_api.py",
        "clinicaltrials": "/Users/athanasios/.gemini/config/plugins/science/skills/clinical_trials_database/scripts/clinical_trials_api.py",
        "uniprot": "/Users/athanasios/.gemini/config/plugins/science/skills/uniprot_database/scripts/uniprot_tools.py"
    }
    
    script_path = script_paths.get(tool_name)
    if not script_path or not os.path.exists(script_path):
        logger.error(f"Script path not found for tool: {tool_name}")
        return None
        
    temp_fd, temp_path = tempfile.mkstemp(suffix=".json")
    os.close(temp_fd)
    
    try:
        # Build command line
        cmd = ["uv", "run", script_path]
        
        if tool_name == "uniprot":
            cmd = ["uv", "run", script_path, subcommand] + extra_args
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if result.returncode != 0:
                logger.error(f"CLI tool '{tool_name}' failed. Exit code: {result.returncode}\nStderr: {result.stderr}")
                return None
            try:
                return json.loads(result.stdout)
            except Exception as json_err:
                logger.error(f"Failed to parse UniProt stdout: {json_err}\nStdout: {result.stdout[:200]}")
                return None
        elif tool_name == "opentargets":
            cmd.extend(["--output", temp_path, subcommand])
            cmd.extend(extra_args)
        elif tool_name == "dbsnp":
            cmd.extend([subcommand])
            cmd.extend(extra_args)
            cmd.extend(["--output", temp_path])
        else:
            cmd.extend([subcommand])
            cmd.extend(extra_args)
            cmd.extend(["--output", temp_path])
            
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        
        if result.returncode != 0:
            logger.error(f"CLI tool '{tool_name}' failed. Exit code: {result.returncode}\nStderr: {result.stderr}")
            return None
            
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            return None
            
        with open(temp_path, "r", encoding="utf-8") as f:
            return json.load(f)
            
    except Exception as e:
        logger.error(f"Error running CLI tool '{tool_name}': {e}")
        return None
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def parse_refseq_chrom(seq_id: str) -> str:
    match = re.search(r"NC_0000(\d+)\.", seq_id)
    if match:
        num = int(match.group(1))
        if num == 23: return "X"
        if num == 24: return "Y"
        return str(num)
    return seq_id

# Async generator for Server-Sent Events (SSE) progress streaming
async def search_stream_generator(query: str):
    query = query.strip()
    is_variant = bool(re.match(r"^rs\d+$", query, re.IGNORECASE))
    
    response_data: Dict[str, Any] = {
        "query": query,
        "type": "variant" if is_variant else "gene",
        "resolved_gene": None,
        "dbsnp": None,
        "clinvar": {
            "variant_summary": None,
            "pathogenic_variants": []
        },
        "gtex": {
            "gencode_id": None,
            "expression": []
        },
        "opentargets": {
            "druggability": None,
            "diseases": []
        },
        "chembl": {
            "target_id": None,
            "mechanisms": [],
            "activities": []
        },
        "clinical_trials": {
            "trials": []
        },
        "protein": None
    }
    
    resolved_gene = None
    rsid = None
    
    # -------------------------------------------------------------
    # STEP 1: GENOMIC RESOLVER (dbSNP / ClinVar)
    # -------------------------------------------------------------
    yield f"data: {json.dumps({'step': 'resolver', 'type': 'status', 'message': 'Running Genomic & Pathogenicity Resolver...'})}\n\n"
    await asyncio.sleep(0.05)
    
    if is_variant:
        rsid = query.lower()
        yield f"data: {json.dumps({'step': 'resolver', 'type': 'log', 'message': f'GET https://api.ncbi.nlm.nih.gov/variation/v0/refsnp/{rsid}'})}\n\n"
        
        dbsnp_data = await asyncio.to_thread(run_cli_tool, "dbsnp", "get-variant", [rsid])
        if dbsnp_data and "error" not in dbsnp_data:
            response_data["dbsnp"] = dbsnp_data
            genes = dbsnp_data.get("genes", [])
            if genes:
                resolved_gene = genes[0]
                response_data["resolved_gene"] = resolved_gene
                yield f"data: {json.dumps({'step': 'resolver', 'type': 'log', 'message': f'dbSNP: Variant associated with gene {resolved_gene}'})}\n\n"
            
            placements = dbsnp_data.get("placements", [])
            if placements:
                placement = placements[0]
                chrom = parse_refseq_chrom(placement.get("seq_id", ""))
                alleles = placement.get("alleles", [])
                ref_allele, alt_allele, pos_1based = "", "", None
                for allele in alleles:
                    if allele.get("is_variant"):
                        alt_allele = allele.get("inserted_sequence", "")
                        ref_allele = allele.get("deleted_sequence", "")
                        if allele.get("position") is not None:
                            pos_1based = int(allele.get("position")) + 1
                            break
                if pos_1based and ref_allele and alt_allele:
                    response_data["dbsnp"]["coordinate"] = f"chr{chrom}:{pos_1based}:{ref_allele}>{alt_allele}"
                    yield f"data: {json.dumps({'step': 'resolver', 'type': 'log', 'message': f'dbSNP: Resolved GRCh38 coordinate chr{chrom}:{pos_1based}:{ref_allele}>{alt_allele}'})}\n\n"
        
        # ClinVar search by rsID
        yield f"data: {json.dumps({'step': 'resolver', 'type': 'log', 'message': f'GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=clinvar&term={rsid}'})}\n\n"
        clinvar_search = await asyncio.to_thread(run_cli_tool, "clinvar", "search", ["--query", rsid])
        if clinvar_search and clinvar_search.get("variant_ids"):
            var_ids = clinvar_search.get("variant_ids")
            if var_ids:
                var_id = var_ids[0]
                yield f"data: {json.dumps({'step': 'resolver', 'type': 'log', 'message': f'GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=clinvar&id={var_id}'})}\n\n"
                clinvar_sum = await asyncio.to_thread(run_cli_tool, "clinvar", "summary", ["--variant_ids", var_id])
                if clinvar_sum and isinstance(clinvar_sum, list) and len(clinvar_sum) > 0:
                    response_data["clinvar"]["variant_summary"] = clinvar_sum[0]
                    if not resolved_gene:
                        cv_genes = clinvar_sum[0].get("genes", [])
                        if cv_genes:
                            resolved_gene = cv_genes[0].get("symbol")
                            response_data["resolved_gene"] = resolved_gene
                
                # ClinVar evidence
                clinvar_ev = await asyncio.to_thread(run_cli_tool, "clinvar", "evidence", ["--variant_id", var_id])
                if clinvar_ev and "allele_info" in clinvar_ev:
                    allele_info = clinvar_ev.get("allele_info", {})
                    chrom = allele_info.get("chromosome", "")
                    pos = allele_info.get("position_start") or allele_info.get("start")
                    ref = allele_info.get("reference_allele")
                    alt = allele_info.get("alternate_allele")
                    if chrom and pos and ref and alt:
                        response_data["clinvar"]["coordinate"] = f"chr{chrom}:{pos}:{ref}>{alt}"
        
        res_gene_name = resolved_gene or "Unknown Gene"
        res_msg = f"Resolved: {query.upper()} -> {res_gene_name}"
        yield f"data: {json.dumps({'step': 'resolver', 'type': 'status', 'message': res_msg})}\n\n"
    else:
        resolved_gene = query.upper()
        response_data["resolved_gene"] = resolved_gene
        yield f"data: {json.dumps({'step': 'resolver', 'type': 'log', 'message': f'GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=clinvar&term={resolved_gene}[gene]+AND+pathogenic[clinsig]'})}\n\n"
        
        clinvar_search = await asyncio.to_thread(run_cli_tool, "clinvar", "search", ["--query", f"{resolved_gene}[gene] AND pathogenic[clinsig]", "--retmax", "5"])
        if clinvar_search and clinvar_search.get("variant_ids"):
            var_ids = clinvar_search.get("variant_ids")
            if var_ids:
                yield f"data: {json.dumps({'step': 'resolver', 'type': 'log', 'message': f'ClinVar: Found {len(var_ids)} pathogenic variants. Summarizing...'})}\n\n"
                clinvar_sums = await asyncio.to_thread(run_cli_tool, "clinvar", "summary", ["--variant_ids"] + var_ids)
                if clinvar_sums and isinstance(clinvar_sums, list):
                    response_data["clinvar"]["pathogenic_variants"] = clinvar_sums
        yield f"data: {json.dumps({'step': 'resolver', 'type': 'status', 'message': f'Gene Pathogenicity resolved for {resolved_gene}'})}\n\n"
    
    # -------------------------------------------------------------
    # STEP 2: TRANSCRIPTOME ATLAS (GTEx)
    # -------------------------------------------------------------
    yield f"data: {json.dumps({'step': 'expression', 'type': 'status', 'message': 'Loading Baseline Tissue Expression Profiles...'})}\n\n"
    await asyncio.sleep(0.05)
    
    if resolved_gene:
        yield f"data: {json.dumps({'step': 'expression', 'type': 'log', 'message': f'GET https://gtexportal.org/api/v2/gene?geneId={resolved_gene}'})}\n\n"
        gtex_id_data = await asyncio.to_thread(run_cli_tool, "gtex", "resolve-gencode-id", [resolved_gene])
        
        if gtex_id_data and "gencode_id" in gtex_id_data:
            gencode_id = gtex_id_data["gencode_id"]
            response_data["gtex"]["gencode_id"] = gencode_id
            yield f"data: {json.dumps({'step': 'expression', 'type': 'log', 'message': f'GTEx: Resolved GENCODE ID {gencode_id}'})}\n\n"
            
            yield f"data: {json.dumps({'step': 'expression', 'type': 'log', 'message': f'GET https://gtexportal.org/api/v2/expression/medianGeneExpression?gencodeId={gencode_id}'})}\n\n"
            gtex_expr = await asyncio.to_thread(run_cli_tool, "gtex", "get-median-expression", [gencode_id])
            if gtex_expr and isinstance(gtex_expr, list):
                response_data["gtex"]["expression"] = gtex_expr
                yield f"data: {json.dumps({'step': 'expression', 'type': 'log', 'message': f'GTEx: Loaded baseline expressions for {len(gtex_expr)} tissues.'})}\n\n"
        
        yield f"data: {json.dumps({'step': 'expression', 'type': 'status', 'message': 'Tissue expression profile loaded.'})}\n\n"
    else:
        yield f"data: {json.dumps({'step': 'expression', 'type': 'status', 'message': 'Skipped expression loader (unresolved gene).'})}\n\n"

    # -------------------------------------------------------------
    # STEP 3: TARGET DRUGGABILITY (Open Targets)
    # -------------------------------------------------------------
    yield f"data: {json.dumps({'step': 'druggability', 'type': 'status', 'message': 'Analyzing Target Druggability & Diseases...'})}\n\n"
    await asyncio.sleep(0.05)
    
    ensembl_id = None
    if response_data["gtex"]["gencode_id"]:
        ensembl_id = response_data["gtex"]["gencode_id"].split(".")[0]
        
    if ensembl_id:
        yield f"data: {json.dumps({'step': 'druggability', 'type': 'log', 'message': f'POST https://api.platform.opentargets.org/api/v4/graphql (Query: target tractability for {ensembl_id})'})}\n\n"
        ot_drug = await asyncio.to_thread(run_cli_tool, "opentargets", "get-target-druggability", [ensembl_id])
        if ot_drug and "target" in ot_drug:
            response_data["opentargets"]["druggability"] = ot_drug["target"]
            
        yield f"data: {json.dumps({'step': 'druggability', 'type': 'log', 'message': f'POST https://api.platform.opentargets.org/api/v4/graphql (Query: associated diseases for {ensembl_id})'})}\n\n"
        ot_diseases = await asyncio.to_thread(run_cli_tool, "opentargets", "get-associated-diseases", [ensembl_id])
        if ot_diseases and "target" in ot_diseases:
            assoc = ot_diseases["target"].get("associatedDiseases", {})
            rows = assoc.get("rows", [])
            cancer_pattern = re.compile(r"cancer|tumor|neoplasm|malignan|leukemia|lymphoma|myeloma|carcinoma|sarcoma|melanoma|glioma|blastoma", re.IGNORECASE)
            oncology_rows = [row for row in rows if cancer_pattern.search(row.get("disease", {}).get("name", ""))]
            
            if len(oncology_rows) < 5:
                response_data["opentargets"]["diseases"] = rows[:10]
            else:
                response_data["opentargets"]["diseases"] = oncology_rows[:10]
            num_diseases = len(response_data["opentargets"]["diseases"])
            ot_log_msg = f"Open Targets: Found {num_diseases} cancer associations."
            yield f"data: {json.dumps({'step': 'druggability', 'type': 'log', 'message': ot_log_msg})}\n\n"
            
        yield f"data: {json.dumps({'step': 'druggability', 'type': 'status', 'message': 'Target druggability analysis completed.'})}\n\n"
    else:
        yield f"data: {json.dumps({'step': 'druggability', 'type': 'status', 'message': 'Skipped druggability (unresolved Ensembl ID).'})}\n\n"

    # -------------------------------------------------------------
    # STEP 4: PHARMACOLOGY & BINDING (ChEMBL)
    # -------------------------------------------------------------
    yield f"data: {json.dumps({'step': 'pharmacology', 'type': 'status', 'message': 'Mining Pharmacology & Compound Binding Affinities...'})}\n\n"
    await asyncio.sleep(0.05)
    
    target_chembl_id = None
    if resolved_gene:
        yield f"data: {json.dumps({'step': 'pharmacology', 'type': 'log', 'message': f'GET https://www.ebi.ac.uk/chembl/api/data/target.json?q={resolved_gene}'})}\n\n"
        chembl_target = await asyncio.to_thread(run_cli_tool, "chembl", "target", ["--search", resolved_gene])
        
        if chembl_target and "targets" in chembl_target:
            targets = chembl_target["targets"]
            
            # Step 1: Look for exact match in pref_name or target component synonyms
            for t in targets:
                if t.get("target_type") == "SINGLE PROTEIN" and t.get("tax_id") == 9606:
                    pref_name = t.get("pref_name", "").upper()
                    synonyms = []
                    for comp in t.get("target_components", []):
                        for syn_obj in comp.get("target_component_synonyms", []):
                            syn_val = syn_obj.get("component_synonym")
                            if syn_val:
                                synonyms.append(syn_val.upper())
                    
                    if resolved_gene == pref_name or resolved_gene in synonyms:
                        target_chembl_id = t.get("target_chembl_id")
                        response_data["chembl"]["target_id"] = target_chembl_id
                        break
            
            # Step 2: Fall back to substring match if no exact match found
            if not target_chembl_id:
                for t in targets:
                    if t.get("target_type") == "SINGLE PROTEIN" and t.get("tax_id") == 9606:
                        pref_name = t.get("pref_name", "").upper()
                        synonyms = []
                        for comp in t.get("target_components", []):
                            for syn_obj in comp.get("target_component_synonyms", []):
                                syn_val = syn_obj.get("component_synonym")
                                if syn_val:
                                    synonyms.append(syn_val.upper())
                                    
                        if resolved_gene in pref_name or any(resolved_gene in syn for syn in synonyms):
                            target_chembl_id = t.get("target_chembl_id")
                            response_data["chembl"]["target_id"] = target_chembl_id
                            break
                            
            # Step 3: Fall back to first human single protein target if still no match
            if not target_chembl_id:
                for t in targets:
                    if t.get("target_type") == "SINGLE PROTEIN" and t.get("tax_id") == 9606:
                        target_chembl_id = t.get("target_chembl_id")
                        response_data["chembl"]["target_id"] = target_chembl_id
                        break
                        
        if target_chembl_id:
            yield f"data: {json.dumps({'step': 'pharmacology', 'type': 'log', 'message': f'ChEMBL: Target resolved to {target_chembl_id}'})}\n\n"
            
            # Fetch approved drugs mechanisms
            yield f"data: {json.dumps({'step': 'pharmacology', 'type': 'log', 'message': f'GET https://www.ebi.ac.uk/chembl/api/data/mechanism.json?target_chembl_id={target_chembl_id}'})}\n\n"
            chembl_mech = await asyncio.to_thread(run_cli_tool, "chembl", "mechanism", ["--filter", f"target_chembl_id={target_chembl_id}", "--limit", "30"])
            if chembl_mech and "mechanisms" in chembl_mech:
                mechs = chembl_mech["mechanisms"]
                mol_ids = list(set([m.get("molecule_chembl_id") for m in mechs if m.get("molecule_chembl_id")]))
                if mol_ids:
                    mols_str = ";".join(mol_ids[:5])
                    chembl_log_msg = f"GET https://www.ebi.ac.uk/chembl/api/data/molecule/set/{mols_str}..."
                    yield f"data: {json.dumps({'step': 'pharmacology', 'type': 'log', 'message': chembl_log_msg})}\n\n"
                    chembl_mols = await asyncio.to_thread(run_cli_tool, "chembl", "molecule", ["--ids", ";".join(mol_ids[:15])])
                    mol_map = {}
                    if chembl_mols and "molecules" in chembl_mols:
                        for mol in chembl_mols["molecules"]:
                            mol_map[mol.get("molecule_chembl_id")] = {
                                "pref_name": mol.get("pref_name") or mol.get("molecule_chembl_id"),
                                "max_phase": mol.get("max_phase", 0),
                                "molecule_type": mol.get("molecule_type")
                            }
                    for m in mechs:
                        m_id = m.get("molecule_chembl_id")
                        m["drug_details"] = mol_map.get(m_id, {"pref_name": m_id, "max_phase": None, "molecule_type": None})
                response_data["chembl"]["mechanisms"] = mechs
                
            # Fetch bioactivities
            yield f"data: {json.dumps({'step': 'pharmacology', 'type': 'log', 'message': f'GET https://www.ebi.ac.uk/chembl/api/data/activity.json?target_chembl_id={target_chembl_id}&standard_type=IC50'})}\n\n"
            chembl_act = await asyncio.to_thread(run_cli_tool, "chembl", "activity", ["--filter", f"target_chembl_id={target_chembl_id}", "standard_type=IC50", "--normalize", "--limit", "20"])
            if chembl_act and "activities" in chembl_act:
                acts = chembl_act["activities"]
                valid_acts = [a for a in acts if a.get("normalized_value_nM") is not None]
                valid_acts.sort(key=lambda x: x["normalized_value_nM"])
                response_data["chembl"]["activities"] = valid_acts[:15]
                num_acts = len(response_data["chembl"]["activities"])
                chembl_act_msg = f"ChEMBL: Extracted {num_acts} binding values."
                yield f"data: {json.dumps({'step': 'pharmacology', 'type': 'log', 'message': chembl_act_msg})}\n\n"
                
        yield f"data: {json.dumps({'step': 'pharmacology', 'type': 'status', 'message': 'Pharmacology details compiled successfully.'})}\n\n"
    else:
        yield f"data: {json.dumps({'step': 'pharmacology', 'type': 'status', 'message': 'Skipped pharmacology (unresolved target).'})}\n\n"

    # -------------------------------------------------------------
    # STEP 5: TRANSLATIONAL MATCHES (ClinicalTrials.gov)
    # -------------------------------------------------------------
    yield f"data: {json.dumps({'step': 'trials', 'type': 'status', 'message': 'Screening Recruiting Clinical Trials...'})}\n\n"
    await asyncio.sleep(0.05)
    
    if resolved_gene:
        yield f"data: {json.dumps({'step': 'trials', 'type': 'log', 'message': f'GET https://clinicaltrials.gov/api/v2/studies?query.cond=cancer&query.intr={resolved_gene}&query.status=RECRUITING'})}\n\n"
        trials_search = await asyncio.to_thread(run_cli_tool, "clinicaltrials", "search", [
            "--condition", "cancer",
            "--intervention", resolved_gene,
            "--status", "RECRUITING",
            "--limit", "15"
        ])
        
        if not trials_search or not trials_search.get("studies"):
            trials_search = await asyncio.to_thread(run_cli_tool, "clinicaltrials", "search", [
                "--condition", "neoplasm",
                "--intervention", resolved_gene,
                "--status", "RECRUITING",
                "--limit", "15"
            ])
            
        if not trials_search or not trials_search.get("studies"):
            trials_search = await asyncio.to_thread(run_cli_tool, "clinicaltrials", "search", [
                "--condition", resolved_gene,
                "--status", "RECRUITING",
                "--limit", "15"
            ])
            
        if trials_search and "studies" in trials_search:
            parsed_trials = []
            for study in trials_search["studies"]:
                protocol = study.get("protocolSection", {})
                ident = protocol.get("identificationModule", {})
                status_mod = protocol.get("statusModule", {})
                desc = protocol.get("descriptionModule", {})
                sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
                eligibility = protocol.get("eligibilityModule", {})
                design = protocol.get("designModule", {})
                locations_mod = protocol.get("contactsLocationsModule", {})
                
                locations = []
                for loc in locations_mod.get("locations", []):
                    geo = loc.get("geoPoint")
                    locations.append({
                        "facility": loc.get("facility", "Research Site"),
                        "city": loc.get("city", ""),
                        "state": loc.get("state", ""),
                        "country": loc.get("country", ""),
                        "lat": geo.get("lat") if geo else None,
                        "lon": geo.get("lon") if geo else None
                    })
                    
                parsed_trials.append({
                    "nct_id": ident.get("nctId"),
                    "title": ident.get("briefTitle"),
                    "status": status_mod.get("overallStatus"),
                    "phase": design.get("phases", ["N/A"])[0] if design.get("phases") else "N/A",
                    "sponsor": sponsor_mod.get("leadSponsor", {}).get("name", "Unknown Sponsor"),
                    "summary": desc.get("briefSummary", "No summary available."),
                    "eligibility": eligibility.get("eligibilityCriteria", ""),
                    "locations": locations
                })
            response_data["clinical_trials"]["trials"] = parsed_trials
            trials_log_msg = f"ClinicalTrials.gov: Mapped {len(parsed_trials)} recruiting trials."
            yield f"data: {json.dumps({'step': 'trials', 'type': 'log', 'message': trials_log_msg})}\n\n"
            
        yield f"data: {json.dumps({'step': 'trials', 'type': 'status', 'message': 'Clinical trials screening completed.'})}\n\n"
    else:
        yield f"data: {json.dumps({'step': 'trials', 'type': 'status', 'message': 'Skipped clinical trials (unresolved query).'})}\n\n"

    # -------------------------------------------------------------
    # STEP 6: MACROMOLECULAR 3D STRUCTURE (UniProt / PDB)
    # -------------------------------------------------------------
    yield f"data: {json.dumps({'step': 'structure', 'type': 'status', 'message': 'Resolving Macromolecular 3D Structure...'})}\n\n"
    await asyncio.sleep(0.05)
    
    if resolved_gene:
        yield f"data: {json.dumps({'step': 'structure', 'type': 'log', 'message': f'GET https://rest.uniprot.org/uniprotkb/search?query=gene:{resolved_gene}+AND+organism_id:9606+AND+reviewed:true'})}\n\n"
        
        uniprot_data = await asyncio.to_thread(run_cli_tool, "uniprot", "search", [
            f"gene:{resolved_gene} AND organism_id:9606 AND reviewed:true",
            "--fields", "accession,id,protein_name,xref_pdb",
            "--format", "json"
        ])
        
        if uniprot_data and "results" in uniprot_data and len(uniprot_data["results"]) > 0:
            entry = uniprot_data["results"][0]
            accession = entry.get("primaryAccession")
            entry_name = entry.get("uniProtkbId")
            
            # Extract full recommended protein name
            desc = entry.get("proteinDescription", {})
            recommended = desc.get("recommendedName", {})
            full_name = recommended.get("fullName", {}).get("value", f"{resolved_gene} protein")
            
            # Extract PDB references
            pdb_refs = []
            for xref in entry.get("uniProtKBCrossReferences", []):
                if xref.get("database") == "PDB":
                    props = {p.get("key"): p.get("value") for p in xref.get("properties", [])}
                    pdb_refs.append({
                        "id": xref.get("id"),
                        "method": props.get("Method", "N/A"),
                        "resolution": props.get("Resolution", "N/A"),
                        "chains": props.get("Chains", "N/A")
                    })
            
            # Sort PDB references by resolution (lower is better)
            def sort_pdb(x):
                res_str = x["resolution"].replace(" A", "").strip()
                try:
                    return float(res_str)
                except ValueError:
                    return 999.0
            
            pdb_refs.sort(key=sort_pdb)
            
            response_data["protein"] = {
                "accession": accession,
                "entry_name": entry_name,
                "full_name": full_name,
                "pdb_ids": pdb_refs[:15] # Top 15 structures
            }
            
            yield f"data: {json.dumps({'step': 'structure', 'type': 'log', 'message': f'UniProt: Resolved accession {accession} ({entry_name}) with {len(pdb_refs)} PDB structures.'})}\n\n"
        
        yield f"data: {json.dumps({'step': 'structure', 'type': 'status', 'message': 'Macromolecular 3D structure compiled.'})}\n\n"
    else:
        yield f"data: {json.dumps({'step': 'structure', 'type': 'status', 'message': 'Skipped structure resolution (unresolved gene).'})}\n\n"

    # -------------------------------------------------------------
    # PIPELINE COMPLETE: STREAM DATA
    # -------------------------------------------------------------
    yield f"data: {json.dumps({'step': 'complete', 'type': 'status', 'message': 'Aggregating files and launching dashboard...', 'data': response_data})}\n\n"

@app.get("/api/search/stream")
def search_stream(query: str = Query(..., description="Query gene symbol or variant rsID")):
    return StreamingResponse(
        search_stream_generator(query),
        media_type="text/event-stream"
    )

# Keeping the synchronous fallback endpoint for verify_backend.py compatibility
@app.get("/api/search")
async def search_sync(query: str = Query(...)):
    data = None
    async for item in search_stream_generator(query):
        if item.startswith("data:"):
            raw_json = item[5:].strip()
            if raw_json:
                try:
                    parsed = json.loads(raw_json)
                    if parsed.get("step") == "complete":
                        data = parsed.get("data")
                except json.JSONDecodeError:
                    continue
                    
    if not data:
        raise HTTPException(status_code=404, detail="Query could not be resolved.")
    return data

# Mount frontend directory for static assets
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
def read_index():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="index.html not found in frontend folder.")
