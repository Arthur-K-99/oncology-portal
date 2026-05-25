import os
import re
import json
import logging
import tempfile
import subprocess
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("oncology-portal")

app = FastAPI(
    title="Oncology Variant & Drug Repurposing Portal API",
    description="Backend API mapping genetic variants and genes to therapeutic insights.",
    version="1.0.0"
)

# Enable CORS for local development
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
        "clinicaltrials": "/Users/athanasios/.gemini/config/plugins/science/skills/clinical_trials_database/scripts/clinical_trials_api.py"
    }
    
    script_path = script_paths.get(tool_name)
    if not script_path or not os.path.exists(script_path):
        logger.error(f"Script path not found for tool: {tool_name}")
        return None
        
    # Create temp file for writing JSON output
    temp_fd, temp_path = tempfile.mkstemp(suffix=".json")
    os.close(temp_fd)
    
    try:
        # Build command line
        cmd = ["uv", "run", script_path]
        
        if tool_name == "opentargets":
            # opentargets expects --output before the subcommand
            cmd.extend(["--output", temp_path, subcommand])
            cmd.extend(extra_args)
        elif tool_name == "dbsnp":
            cmd.extend([subcommand])
            cmd.extend(extra_args)
            cmd.extend(["--output", temp_path])
        else:
            # clinvar, gtex, chembl, clinicaltrials expect subcommand, args, then --output
            cmd.extend([subcommand])
            cmd.extend(extra_args)
            cmd.extend(["--output", temp_path])
            
        logger.info(f"Executing: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        
        if result.returncode != 0:
            logger.error(f"CLI tool '{tool_name}' failed. Exit code: {result.returncode}\nStderr: {result.stderr}")
            return None
            
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            logger.error(f"CLI tool '{tool_name}' did not write output or file is empty")
            return None
            
        with open(temp_path, "r", encoding="utf-8") as f:
            return json.load(f)
            
    except subprocess.TimeoutExpired:
        logger.error(f"CLI tool '{tool_name}' timed out after 90 seconds.")
        return None
    except Exception as e:
        logger.error(f"Error running CLI tool '{tool_name}': {e}")
        return None
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

# Extract chromosome from RefSeq accession (e.g., NC_000019.10 -> 19, NC_000023.11 -> X)
def parse_refseq_chrom(seq_id: str) -> str:
    match = re.search(r"NC_0000(\d+)\.", seq_id)
    if match:
        num = int(match.group(1))
        if num == 23:
            return "X"
        if num == 24:
            return "Y"
        return str(num)
    return seq_id

@app.get("/api/search")
def search(query: str = Query(..., description="Gene symbol (e.g. EGFR) or Variant rsID (e.g. rs121913343)")):
    query = query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
        
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
        }
    }
    
    resolved_gene = None
    rsid = None
    
    # -------------------------------------------------------------
    # 1. RESOLVE GENE AND VARIANT DETAILS
    # -------------------------------------------------------------
    if is_variant:
        rsid = query.lower()
        logger.info(f"Processing variant rsID search: {rsid}")
        
        # Query dbSNP
        dbsnp_data = run_cli_tool("dbsnp", "get-variant", [rsid])
        if dbsnp_data and "error" not in dbsnp_data:
            response_data["dbsnp"] = dbsnp_data
            # Extract associated gene symbol
            genes = dbsnp_data.get("genes", [])
            if genes:
                resolved_gene = genes[0]
                response_data["resolved_gene"] = resolved_gene
                logger.info(f"Resolved rsID {rsid} to gene {resolved_gene}")
                
            # Reconstruct coordinate notation chrom:pos:ref>alt
            placements = dbsnp_data.get("placements", [])
            if placements:
                placement = placements[0]
                chrom = parse_refseq_chrom(placement.get("seq_id", ""))
                alleles = placement.get("alleles", [])
                ref_allele = ""
                alt_allele = ""
                pos_1based = None
                
                # Find the variant allele
                for allele in alleles:
                    if allele.get("is_variant"):
                        alt_allele = allele.get("inserted_sequence", "")
                        ref_allele = allele.get("deleted_sequence", "")
                        # dbSNP SPDI position is 0-based
                        if allele.get("position") is not None:
                            pos_1based = int(allele.get("position")) + 1
                            break
                            
                if pos_1based and ref_allele and alt_allele:
                    response_data["dbsnp"]["coordinate"] = f"chr{chrom}:{pos_1based}:{ref_allele}>{alt_allele}"
        else:
            logger.warning(f"Could not resolve variant in dbSNP: {rsid}")
            
        # Query ClinVar details for this rsID
        clinvar_search = run_cli_tool("clinvar", "search", ["--query", rsid])
        if clinvar_search and clinvar_search.get("variant_ids"):
            var_ids = clinvar_search.get("variant_ids")
            if var_ids:
                var_id = var_ids[0]
                clinvar_sum = run_cli_tool("clinvar", "summary", ["--variant_ids", var_id])
                if clinvar_sum and isinstance(clinvar_sum, list) and len(clinvar_sum) > 0:
                    response_data["clinvar"]["variant_summary"] = clinvar_sum[0]
                    # Fallback gene resolution from ClinVar if dbSNP missed it
                    if not resolved_gene:
                        cv_genes = clinvar_sum[0].get("genes", [])
                        if cv_genes:
                            resolved_gene = cv_genes[0].get("symbol")
                            response_data["resolved_gene"] = resolved_gene
                            logger.info(f"Resolved rsID {rsid} to gene {resolved_gene} via ClinVar")
                            
                # Get coordinates from ClinVar evidence
                clinvar_ev = run_cli_tool("clinvar", "evidence", ["--variant_id", var_id])
                if clinvar_ev and "allele_info" in clinvar_ev:
                    allele_info = clinvar_ev.get("allele_info", {})
                    chrom = allele_info.get("chromosome", "")
                    pos = allele_info.get("position_start") or allele_info.get("start")
                    ref = allele_info.get("reference_allele")
                    alt = allele_info.get("alternate_allele")
                    if chrom and pos and ref and alt:
                        response_data["clinvar"]["coordinate"] = f"chr{chrom}:{pos}:{ref}>{alt}"
    else:
        resolved_gene = query.upper()
        response_data["resolved_gene"] = resolved_gene
        logger.info(f"Processing gene symbol search: {resolved_gene}")
        
        # Query ClinVar for top pathogenic variants in this gene
        clinvar_search = run_cli_tool("clinvar", "search", ["--query", f"{resolved_gene}[gene] AND pathogenic[clinsig]", "--retmax", "5"])
        if clinvar_search and clinvar_search.get("variant_ids"):
            var_ids = clinvar_search.get("variant_ids")
            if var_ids:
                clinvar_sums = run_cli_tool("clinvar", "summary", ["--variant_ids"] + var_ids)
                if clinvar_sums and isinstance(clinvar_sums, list):
                    response_data["clinvar"]["pathogenic_variants"] = clinvar_sums

    # -------------------------------------------------------------
    # 2. RUN GENE-LEVEL PIPELINE IF GENE IS RESOLVED
    # -------------------------------------------------------------
    if resolved_gene:
        # A. GTEx Baseline Expression
        gtex_id_data = run_cli_tool("gtex", "resolve-gencode-id", [resolved_gene])
        if gtex_id_data and "gencode_id" in gtex_id_data:
            gencode_id = gtex_id_data["gencode_id"]
            response_data["gtex"]["gencode_id"] = gencode_id
            
            # Fetch median expressions
            gtex_expr = run_cli_tool("gtex", "get-median-expression", [gencode_id])
            if gtex_expr and isinstance(gtex_expr, list):
                response_data["gtex"]["expression"] = gtex_expr
                
        # B. Open Targets Druggability & Disease Associations
        # Strip version suffix (e.g. ENSG00000130203.10 -> ENSG00000130203)
        ensembl_id = None
        if response_data["gtex"]["gencode_id"]:
            ensembl_id = response_data["gtex"]["gencode_id"].split(".")[0]
            
        if ensembl_id:
            # Get Druggability
            ot_drug = run_cli_tool("opentargets", "get-target-druggability", [ensembl_id])
            if ot_drug and "target" in ot_drug:
                response_data["opentargets"]["druggability"] = ot_drug["target"]
                
            # Get Associated Diseases
            ot_diseases = run_cli_tool("opentargets", "get-associated-diseases", [ensembl_id])
            if ot_diseases and "target" in ot_diseases:
                assoc = ot_diseases["target"].get("associatedDiseases", {})
                rows = assoc.get("rows", [])
                
                # Filter for oncology-related diseases (contains cancer, tumor, neoplasm, blastoma, leukemia, etc.)
                cancer_pattern = re.compile(r"cancer|tumor|neoplasm|malignan|leukemia|lymphoma|myeloma|carcinoma|sarcoma|melanoma|glioma|blastoma", re.IGNORECASE)
                oncology_rows = []
                for row in rows:
                    disease_name = row.get("disease", {}).get("name", "")
                    if cancer_pattern.search(disease_name):
                        oncology_rows.append(row)
                        
                # If we don't have enough oncology rows, return general associations
                if len(oncology_rows) < 5:
                    response_data["opentargets"]["diseases"] = rows[:10]
                else:
                    response_data["opentargets"]["diseases"] = oncology_rows[:10]

        # C. ChEMBL Target, Drug Mechanisms & Bioactivities
        chembl_target = run_cli_tool("chembl", "target", ["--search", resolved_gene])
        target_chembl_id = None
        
        if chembl_target and "targets" in chembl_target:
            targets = chembl_target["targets"]
            # Look for human single protein target matching the gene symbol
            for t in targets:
                if t.get("target_type") == "SINGLE PROTEIN" and t.get("tax_id") == 9606:
                    pref_name = t.get("pref_name", "").upper()
                    if resolved_gene in pref_name or resolved_gene in [syn.get("component_synonym", "").upper() for syn in t.get("target_components", [])]:
                        target_chembl_id = t.get("target_chembl_id")
                        response_data["chembl"]["target_id"] = target_chembl_id
                        break
            
            # Fallback to first single protein human target if no exact gene match
            if not target_chembl_id:
                for t in targets:
                    if t.get("target_type") == "SINGLE PROTEIN" and t.get("tax_id") == 9606:
                        target_chembl_id = t.get("target_chembl_id")
                        response_data["chembl"]["target_id"] = target_chembl_id
                        break
                        
        if target_chembl_id:
            # Query approved/clinical mechanisms
            chembl_mech = run_cli_tool("chembl", "mechanism", ["--filter", f"target_chembl_id={target_chembl_id}", "--limit", "30"])
            if chembl_mech and "mechanisms" in chembl_mech:
                mechs = chembl_mech["mechanisms"]
                # Resolve drug molecule names for these mechanisms in a batch if possible, or extract details
                mol_ids = list(set([m.get("molecule_chembl_id") for m in mechs if m.get("molecule_chembl_id")]))
                
                if mol_ids:
                    # Query molecule names for these IDs
                    mol_ids_str = ";".join(mol_ids[:15])  # Cap at 15 molecules
                    chembl_mols = run_cli_tool("chembl", "molecule", ["--ids", mol_ids_str])
                    
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
                        m["drug_details"] = mol_map.get(m_id, {
                            "pref_name": m_id,
                            "max_phase": None,
                            "molecule_type": None
                        })
                response_data["chembl"]["mechanisms"] = mechs
                
            # Query bioactivity values (IC50)
            chembl_act = run_cli_tool("chembl", "activity", ["--filter", f"target_chembl_id={target_chembl_id}", "standard_type=IC50", "--normalize", "--limit", "20"])
            if chembl_act and "activities" in chembl_act:
                # Filter for activities with normalized value and sort by binding affinity (lowest IC50 is strongest binding)
                acts = chembl_act["activities"]
                valid_acts = [a for a in acts if a.get("normalized_value_nM") is not None]
                valid_acts.sort(key=lambda x: x["normalized_value_nM"])
                response_data["chembl"]["activities"] = valid_acts[:15]

        # D. ClinicalTrials.gov Recruiting Trials
        # First query: search for condition="cancer" and intervention=gene_symbol
        trials_search = run_cli_tool("clinicaltrials", "search", [
            "--condition", "cancer",
            "--intervention", resolved_gene,
            "--status", "RECRUITING",
            "--limit", "15"
        ])
        
        # If no trials are found, try searching condition="neoplasm" and intervention=gene_symbol
        if not trials_search or not trials_search.get("studies"):
            trials_search = run_cli_tool("clinicaltrials", "search", [
                "--condition", "neoplasm",
                "--intervention", resolved_gene,
                "--status", "RECRUITING",
                "--limit", "15"
            ])
            
        # Fallback to search condition=gene_symbol if still empty
        if not trials_search or not trials_search.get("studies"):
            trials_search = run_cli_tool("clinicaltrials", "search", [
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
                
                # Extract coordinates and cities
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

    # If we could not resolve a gene at all, throw a 404
    if is_variant and not response_data["dbsnp"] and not response_data["clinvar"]["variant_summary"]:
        raise HTTPException(status_code=404, detail=f"Variant rsID '{query}' could not be resolved.")
    elif not is_variant and not resolved_gene:
        raise HTTPException(status_code=404, detail=f"Gene symbol '{query}' could not be resolved.")
        
    return response_data

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
