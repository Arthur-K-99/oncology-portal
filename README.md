# Oncology Variant & Drug Repurposing Portal

An interactive clinical genomics web portal mapping cancer-associated genes or genomic variants (rsIDs) to clinical significance, tissue-specific expressions, druggability profiles, and actively recruiting clinical trials. 

This portal acts as a translational pipeline for researchers and clinicians to query genetic aberrations and instantly discover therapeutic insights and patient-matching clinical trials.

---

## 🔬 Scientific Data Integrations

The portal aggregates multi-modal data in real-time from six scientific databases:
1. **dbSNP**: Maps genomic variants to standard rsIDs and computes GRCh38 placements (coordinates, reference, and alternate alleles).
2. **ClinVar**: Retrieves clinical pathogenicity classifications (Pathogenic, Benign, VUS), star ratings (review status strength), and associated phenotypes.
3. **GTEx (Genotype-Tissue Expression)**: Resolves GENCODE IDs and fetches baseline tissue-specific mRNA expression profiles (in Transcripts Per Million - TPM) to assess target safety and off-target tissue risk.
4. **Open Targets**: Assesses target druggability (tractability for Small Molecules, Antibodies, or degraders) and lists cancer-associated disease scores.
5. **ChEMBL**: Resolves biological targets, retrieves approved clinical drug mechanisms, and maps investigational compound binding affinities ($IC_{50}$ values in nM).
6. **ClinicalTrials.gov**: Queries recruiting oncology clinical trials matching the target, extracting trial phases, lead sponsors, and site location coordinates (`geoPoint`) for mapping.

---

## 🎨 Design & Visual Deliverables

The application is styled with a premium **dark glassmorphism dashboard** interface featuring:
- **Search Header**: Auto-completion suggestions and quick-badge queries.
- **Pathogenicity Card**: Standardized variant titles, ACMG significance badges, and clinical review status stars.
- **Dynamic Expression Chart**: A custom Chart.js horizontal bar chart visualizing baseline tissue distributions.
- **Drug Discovery Table**: A tab-switched table displaying approved/investigational drugs, clinical phases, target actions, and normalized nanomolar $IC_{50}$ binding affinities.
- **Clinical Trials Map & List**: A Leaflet.js interactive dark-themed map plotting recruiting clinical facilities, linked with a scrollable list of trials supporting phase filtering and center-on-marker navigation.

---

## 🛠️ Technology Stack

- **Frontend**: HTML5, Vanilla CSS3 (Custom Glassmorphism), Vanilla JavaScript, Leaflet.js (mapping), Chart.js (charts), Lucide Icons (vector iconography).
- **Backend**: FastAPI, Uvicorn, Python 3.10+ (Subprocess integrations with scientific database CLI wrappers).
- **Package Manager**: `uv` (fast, single-binary Python package manager).

---

## 🚀 Getting Started

### Prerequisites
Make sure you have `uv` installed. If you don't, you can install it using:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/YOUR_USERNAME/oncology-portal.git
   cd oncology-portal
   ```

2. Initialize and sync dependencies:
   ```bash
   uv sync
   ```
   This will automatically set up a virtual environment (`.venv`) and install all required packages (FastAPI, Uvicorn, Requests, HTTPX, and python-dotenv).

3. *(Optional)* Add NCBI API Key:
   An NCBI API key is recommended to raise the rate limit from 3 to 10 requests per second. Create or edit a `.env` file in your home directory (`~/.env`) and append your key:
   ```bash
   echo "NCBI_API_KEY=your_key_here" >> ~/.env
   ```

### Running the Portal
Run the development server using:
```bash
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```
Once the server starts, open your browser and navigate to:
**[http://localhost:8000](http://localhost:8000)**

---

## 🧪 Automated Testing

You can run the automated validation test suite (which validates endpoint response structures for both genes and variants) using:
```bash
uv run verify_backend.py
```
If successful, the output will display: `ALL TESTS PASSED SUCCESSFULLY! The backend is verified and ready.`
