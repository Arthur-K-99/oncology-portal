import sys
import logging
from fastapi.testclient import TestClient

# Import the FastAPI app
try:
    from backend.main import app, parse_refseq_chrom
except ImportError as e:
    print(f"Error importing app: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify-backend")

client = TestClient(app)

def test_parse_refseq_chrom():
    logger.info("Testing RefSeq chromosome parser...")
    assert parse_refseq_chrom("NC_000019.10") == "19"
    assert parse_refseq_chrom("NC_000001.11") == "1"
    assert parse_refseq_chrom("NC_000023.11") == "X"
    assert parse_refseq_chrom("NC_000024.10") == "Y"
    assert parse_refseq_chrom("NT_123456") == "NT_123456"
    logger.info("RefSeq parser verified successfully.")

def verify_search_gene():
    logger.info("Testing gene search endpoint: GET /api/search?query=EGFR")
    response = client.get("/api/search?query=EGFR")
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    
    # Assert JSON Structure
    assert data["query"] == "EGFR"
    assert data["type"] == "gene"
    assert data["resolved_gene"] == "EGFR"
    
    # Assert ClinVar Pathogenic variants list is populated
    assert "clinvar" in data
    assert isinstance(data["clinvar"]["pathogenic_variants"], list)
    logger.info(f"ClinVar pathogenic variants found: {len(data['clinvar']['pathogenic_variants'])}")
    
    # Assert GTEx baseline expression is populated
    assert "gtex" in data
    assert data["gtex"]["gencode_id"] is not None
    assert isinstance(data["gtex"]["expression"], list)
    logger.info(f"GTEx GENCODE resolved ID: {data['gtex']['gencode_id']}")
    logger.info(f"GTEx expression tissue sites returned: {len(data['gtex']['expression'])}")
    
    # Assert Open Targets druggability and diseases are resolved
    assert "opentargets" in data
    assert data["opentargets"]["druggability"] is not None
    assert isinstance(data["opentargets"]["diseases"], list)
    logger.info(f"Open Targets disease associations: {len(data['opentargets']['diseases'])}")
    
    # Assert ChEMBL target and drugs are resolved
    assert "chembl" in data
    assert data["chembl"]["target_id"] is not None
    assert isinstance(data["chembl"]["mechanisms"], list)
    assert isinstance(data["chembl"]["activities"], list)
    logger.info(f"ChEMBL Target ID resolved: {data['chembl']['target_id']}")
    logger.info(f"ChEMBL drug mechanisms found: {len(data['chembl']['mechanisms'])}")
    logger.info(f"ChEMBL bioactivities found: {len(data['chembl']['activities'])}")
    
    # Assert Clinical Trials are resolved
    assert "clinical_trials" in data
    assert isinstance(data["clinical_trials"]["trials"], list)
    logger.info(f"ClinicalTrials.gov recruiting trials found: {len(data['clinical_trials']['trials'])}")
    
    # Check that leaflet coordinates are present
    if data["clinical_trials"]["trials"]:
        first_trial = data["clinical_trials"]["trials"][0]
        assert "locations" in first_trial
        logger.info("Clinical trials verification passed.")

def verify_search_variant():
    logger.info("Testing variant search endpoint: GET /api/search?query=rs121913343")
    response = client.get("/api/search?query=rs121913343")
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    
    # Assert JSON Structure for Variant
    assert data["query"] == "rs121913343"
    assert data["type"] == "variant"
    assert data["resolved_gene"] == "TP53"
    
    # dbSNP check
    assert "dbsnp" in data
    assert data["dbsnp"] is not None
    assert "coordinate" in data["dbsnp"]
    logger.info(f"Resolved VCF coordinate for rs121913343: {data['dbsnp']['coordinate']}")
    
    # ClinVar summary check for rsID
    assert data["clinvar"]["variant_summary"] is not None
    assert "clinical_significance" in data["clinvar"]["variant_summary"]
    logger.info(f"ClinVar Clinical Significance for rs121913343: {data['clinvar']['variant_summary']['clinical_significance']}")
    
    # Check that gene expression resolved for the associated gene TP53
    assert data["gtex"]["gencode_id"] is not None
    logger.info(f"Successfully ran secondary gene pipeline on associated gene {data['resolved_gene']}.")

def verify_static_routes():
    logger.info("Testing static routes serving index.html...")
    response = client.get("/")
    assert response.status_code == 200
    assert "<title>" in response.text
    logger.info("Static index route verified successfully.")

def main():
    logger.info("Starting automated backend validation tests...")
    try:
        test_parse_refseq_chrom()
        verify_static_routes()
        verify_search_gene()
        verify_search_variant()
        logger.info("\nALL TESTS PASSED SUCCESSFULLY! The backend is verified and ready.")
    except AssertionError as e:
        logger.error(f"\nTEST FAILURE: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\nUnexpected error during test execution: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
