document.addEventListener('DOMContentLoaded', () => {
    // Icons initialization
    lucide.createIcons();

    // DOM Elements
    const searchForm = document.getElementById('search-form');
    const searchInput = document.getElementById('search-input');
    const exampleBadges = document.querySelectorAll('.example-badge');
    const loader = document.getElementById('loader');
    const placeholderState = document.getElementById('placeholder-state');
    const dashboard = document.getElementById('dashboard');

    // Metadata Fields
    const metaType = document.getElementById('meta-type');
    const metaTitle = document.getElementById('meta-title');
    const metaSubtitle = document.getElementById('meta-subtitle');
    const metaCoords = document.getElementById('meta-coords');
    const metaCoordsContainer = document.getElementById('meta-coords-container');

    // Views
    const singleVarView = document.getElementById('single-var-view');
    const geneVarView = document.getElementById('gene-var-view');

    // Single Variant Fields
    const varSig = document.getElementById('var-sig');
    const varStars = document.getElementById('var-stars');
    const varTitle = document.getElementById('var-title');
    const varReviewStatus = document.getElementById('var-review-status');
    const varLastEval = document.getElementById('var-last-eval');
    const varType = document.getElementById('var-type');
    const varPhenotypes = document.getElementById('var-phenotypes');

    // Gene Pathogenic Table
    const geneVariantsList = document.getElementById('gene-variants-list');

    // Tractability Badges
    const tractabilityBadges = document.getElementById('tractability-badges');

    // Drug Tables
    const approvedDrugsList = document.getElementById('approved-drugs-list');
    const bindingAffinitiesList = document.getElementById('binding-affinities-list');

    // Clinical Trials List and Filters
    const trialsList = document.getElementById('trials-list');
    const phaseFilter = document.getElementById('trial-phase-filter');

    // Global Instances
    let expressionChartInstance = null;
    let leafletMapInstance = null;
    let mapMarkersGroup = null;
    let molViewerInstance = null;
    let currentData = null; // Caches results for filtering

    // -------------------------------------------------------------
    // EVENT LISTENERS & SETUP
    // -------------------------------------------------------------

    // Quick selection badges
    exampleBadges.forEach(badge => {
        badge.addEventListener('click', () => {
            searchInput.value = badge.getAttribute('data-val');
            searchForm.dispatchEvent(new Event('submit'));
        });
    });

    // Console Log & Pipeline helpers
    const consoleLog = document.getElementById('console-log');
    const pipelineSteps = ['resolver', 'expression', 'druggability', 'pharmacology', 'trials', 'structure'];
    
    function appendConsoleLog(text, className) {
        const line = document.createElement('div');
        line.className = `log-line ${className || 'log-system'}`;
        line.textContent = `[${new Date().toLocaleTimeString()}] ${text}`;
        consoleLog.appendChild(line);
        consoleLog.scrollTop = consoleLog.scrollHeight;
    }

    function resetPipeline() {
        pipelineSteps.forEach(step => {
            const node = document.getElementById(`step-${step}`);
            const detail = document.getElementById(`detail-${step}`);
            node.className = 'step-node'; // remove running / completed
            
            if (step === 'resolver') detail.textContent = 'Pending initialization...';
            else if (step === 'expression') detail.textContent = 'Waiting for gene resolution...';
            else if (step === 'druggability') detail.textContent = 'Waiting for expression data...';
            else if (step === 'pharmacology') detail.textContent = 'Waiting for druggability profile...';
            else if (step === 'trials') detail.textContent = 'Waiting for drug listings...';
            else if (step === 'structure') detail.textContent = 'Waiting for clinical trials...';
        });
        
        consoleLog.innerHTML = '<div class="log-line log-system">OncoPortal shell initialized. Ready for query analysis.</div>';
    }
    
    function updatePipelineProgress(currentStep, isRunning, message) {
        const currentIndex = pipelineSteps.indexOf(currentStep);
        
        pipelineSteps.forEach((step, idx) => {
            const node = document.getElementById(`step-${step}`);
            const detail = document.getElementById(`detail-${step}`);
            
            if (idx < currentIndex) {
                node.className = 'step-node completed';
            } else if (idx === currentIndex) {
                if (isRunning) {
                    node.className = 'step-node running';
                    detail.textContent = message;
                } else {
                    node.className = 'step-node completed';
                    detail.textContent = message;
                }
            } else {
                node.className = 'step-node';
            }
        });
    }

    // Form Search Submission via EventSource (SSE)
    searchForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const query = searchInput.value.trim();
        if (!query) return;

        // Reset UI
        placeholderState.classList.add('hidden');
        dashboard.classList.add('hidden');
        loader.classList.remove('hidden');
        
        // Reset pipeline and console
        resetPipeline();
        appendConsoleLog(`Establishing connection to query pipeline for: ${query.toUpperCase()}...`, 'log-system');

        // Connect to FastAPI SSE Stream
        const eventSource = new EventSource(`/api/search/stream?query=${encodeURIComponent(query)}`);

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                
                if (data.step === 'complete') {
                    appendConsoleLog(data.message, 'log-success');
                    appendConsoleLog('Query pipeline stream completed successfully. Launching dashboard.', 'log-success');
                    eventSource.close();
                    
                    // Cache data
                    currentData = data.data;
                    
                    // Render and transition with a tiny delay to let the user see the complete state
                    setTimeout(() => {
                        renderDashboard(currentData);
                        loader.classList.add('hidden');
                        dashboard.classList.remove('hidden');
                    }, 800);
                    
                } else {
                    // Update steps and log to console
                    if (data.type === 'status') {
                        const isDone = data.message.includes('loaded') || data.message.includes('completed') || data.message.includes('resolved');
                        updatePipelineProgress(data.step, !isDone, data.message);
                        appendConsoleLog(data.message, 'log-success');
                    } else if (data.type === 'log') {
                        const isRequest = data.message.startsWith('GET') || data.message.startsWith('POST');
                        appendConsoleLog(data.message, isRequest ? 'log-api' : 'log-system');
                    }
                }
            } catch (err) {
                appendConsoleLog(`Error parsing stream event: ${err.message}`, 'log-warning');
            }
        };

        eventSource.onerror = (err) => {
            eventSource.close();
            appendConsoleLog('Pipeline pipeline connection lost or failed. Query cancelled.', 'log-warning');
            setTimeout(() => {
                loader.classList.add('hidden');
                placeholderState.classList.remove('hidden');
                alert(`Search failed: Connection to streaming endpoint lost.`);
            }, 1500);
        };
    });

    // Tab Switching Logic
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-tab');
            
            // Remove active states
            btn.parentElement.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.parentElement.parentElement.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            
            // Add active states
            btn.classList.add('active');
            document.getElementById(targetTab).classList.add('active');
        });
    });

    // Phase Filter Dropdown
    phaseFilter.addEventListener('change', () => {
        if (currentData) {
            renderClinicalTrials(currentData.clinical_trials.trials);
        }
    });

    // -------------------------------------------------------------
    // RENDER FUNCTIONS
    // -------------------------------------------------------------

    function renderDashboard(data) {
        // 1. Render Context Card
        metaType.textContent = data.type.toUpperCase();
        metaType.className = `search-type-badge ${data.type === 'variant' ? 'sig-pathogenic' : 'sig-benign'}`;
        metaTitle.textContent = data.query.toUpperCase();
        
        let subtitle = '';
        let coords = 'N/A';
        
        if (data.type === 'variant') {
            subtitle = data.resolved_gene ? `Cancer variant associated with gene: ${data.resolved_gene}` : 'Variant analysis details';
            coords = data.dbsnp?.coordinate || data.clinvar?.coordinate || 'N/A';
            metaCoordsContainer.classList.remove('hidden');
        } else {
            subtitle = data.resolved_gene ? `Cancer Oncogene: ${data.resolved_gene}` : 'Gene analysis details';
            metaCoordsContainer.classList.add('hidden');
        }
        
        metaSubtitle.textContent = subtitle;
        metaCoords.textContent = coords;

        // 2. Render Pathogenicity section
        if (data.type === 'variant') {
            singleVarView.classList.remove('hidden');
            geneVarView.classList.add('hidden');
            
            const summary = data.clinvar.variant_summary;
            if (summary) {
                varTitle.textContent = summary.title || data.query;
                
                // Significance status
                const clinsig = (summary.clinical_significance || 'unknown').toLowerCase();
                varSig.textContent = summary.clinical_significance || 'unknown';
                varSig.className = 'sig-badge';
                if (clinsig.includes('pathogenic')) {
                    varSig.classList.add('sig-pathogenic');
                } else if (clinsig.includes('benign')) {
                    varSig.classList.add('sig-benign');
                } else if (clinsig.includes('uncertain') || clinsig.includes('vus')) {
                    varSig.classList.add('sig-uncertain');
                } else {
                    varSig.classList.add('sig-other');
                }
                
                // ACMG Stars rating
                const starsCount = getClinVarStarsCount(summary.review_status);
                varStars.innerHTML = '';
                for (let i = 0; i < 4; i++) {
                    const starIcon = document.createElement('i');
                    starIcon.setAttribute('data-lucide', 'star');
                    if (i >= starsCount) {
                        starIcon.style.color = '#4b5563'; // unlit star
                        starIcon.style.fill = 'transparent';
                    }
                    varStars.appendChild(starIcon);
                }
                
                varReviewStatus.textContent = summary.review_status || 'N/A';
                varLastEval.textContent = summary.last_evaluated || 'N/A';
                varType.textContent = summary.variation_type || data.dbsnp?.variant_type || 'N/A';
                
                // Phenotypes
                varPhenotypes.innerHTML = '';
                const phenotypes = summary.phenotypes || [];
                if (phenotypes.length > 0) {
                    phenotypes.forEach(pheno => {
                        const pill = document.createElement('span');
                        pill.className = 'pill pill-oncology';
                        pill.textContent = pheno;
                        varPhenotypes.appendChild(pill);
                    });
                } else {
                    varPhenotypes.innerHTML = '<span class="no-data">No reported phenotypes</span>';
                }
            } else {
                // If ClinVar summary missed but dbSNP worked, fill basic details
                varTitle.textContent = `rsID ${data.query}`;
                varSig.textContent = data.dbsnp?.clinical_significances?.[0] || 'Unknown';
                varSig.className = 'sig-badge sig-other';
                varStars.innerHTML = '';
                varReviewStatus.textContent = 'unreviewed';
                varLastEval.textContent = 'N/A';
                varType.textContent = data.dbsnp?.variant_type || 'N/A';
                varPhenotypes.innerHTML = '<span class="no-data">Details missing from ClinVar</span>';
            }
        } else {
            // Gene Mode: list variants
            singleVarView.classList.add('hidden');
            geneVarView.classList.remove('hidden');
            
            geneVariantsList.innerHTML = '';
            const variants = data.clinvar.pathogenic_variants || [];
            if (variants.length > 0) {
                variants.forEach(v => {
                    const tr = document.createElement('tr');
                    
                    const starsCount = getClinVarStarsCount(v.review_status);
                    let starsHtml = '';
                    for(let i=0; i<starsCount; i++) starsHtml += '★';
                    for(let i=starsCount; i<4; i++) starsHtml += '☆';
                    
                    const sig = (v.clinical_significance || 'pathogenic').toLowerCase();
                    let badgeClass = 'sig-badge sig-other';
                    if (sig.includes('pathogenic')) badgeClass = 'sig-badge sig-pathogenic';
                    else if (sig.includes('benign')) badgeClass = 'sig-badge sig-benign';
                    
                    tr.innerHTML = `
                        <td style="font-family: var(--font-mono); font-weight: 500;">${v.title}</td>
                        <td class="text-center"><span class="${badgeClass}" style="font-size:10px; padding: 4px 8px;">${v.clinical_significance}</span></td>
                        <td class="text-center" style="color: var(--neon-yellow);">${starsHtml}</td>
                        <td>${v.last_evaluated || 'N/A'}</td>
                    `;
                    geneVariantsList.appendChild(tr);
                });
            } else {
                geneVariantsList.innerHTML = `<tr><td colspan="4" class="no-data">No reported pathogenic variants found in ClinVar for this gene.</td></tr>`;
            }
        }
        lucide.createIcons();

        // 3. Render GTEx expression bar chart
        renderExpressionChart(data.gtex.expression, data.resolved_gene);

        // 4. Render Drug Discovery & Target Tractability
        renderDruggability(data.opentargets.druggability);
        renderApprovedDrugs(data.chembl.mechanisms);
        renderBindingAffinities(data.chembl.activities);

        // 5. Render Clinical Trials
        renderClinicalTrials(data.clinical_trials.trials);

        // 6. Render Macromolecular 3D Structure
        renderProteinStructure(data.protein);
    }

    // ACMG Stars Rating converter
    function getClinVarStarsCount(reviewStatus) {
        if (!reviewStatus) return 0;
        const status = reviewStatus.toLowerCase();
        if (status.includes("practice guideline")) return 4;
        if (status.includes("expert panel")) return 3;
        if (status.includes("multiple submitters") && status.includes("no conflicts")) return 2;
        if (status.includes("single submitter") || status.includes("criteria provided")) return 1;
        return 0;
    }

    // 3. GTEx Expression Chart rendering using Chart.js
    function renderExpressionChart(expressionData, geneSymbol) {
        if (expressionChartInstance) {
            expressionChartInstance.destroy();
        }

        const ctx = document.getElementById('expression-chart').getContext('2d');

        if (!expressionData || expressionData.length === 0) {
            ctx.clearRect(0, 0, 400, 300);
            document.getElementById('expression-chart').parentElement.innerHTML = `<p class="no-data">No GTEx baseline expression data found for ${geneSymbol}</p>`;
            return;
        }

        // Sort by median and take top 10 tissues for readable display
        const sortedExpr = [...expressionData].sort((a, b) => b.median - a.median).slice(0, 10);
        
        const labels = sortedExpr.map(item => item.tissueSiteDetailId.replace(/_/g, ' '));
        const values = sortedExpr.map(item => item.median);

        // Gradient styling
        const gradient = ctx.createLinearGradient(0, 0, 400, 0);
        gradient.addColorStop(0, 'rgba(0, 242, 254, 0.2)');
        gradient.addColorStop(1, 'rgba(161, 140, 209, 0.85)');

        expressionChartInstance = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Median Expression (TPM)',
                    data: values,
                    backgroundColor: gradient,
                    borderColor: 'var(--neon-blue)',
                    borderWidth: 1,
                    borderRadius: 4,
                    hoverBackgroundColor: 'rgba(0, 242, 254, 0.6)'
                }]
            },
            options: {
                indexAxis: 'y', // Horizontal bars
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        backgroundColor: '#0d1426',
                        titleColor: '#fff',
                        bodyColor: '#00f2fe',
                        borderColor: 'rgba(255,255,255,0.08)',
                        borderWidth: 1,
                        callbacks: {
                            label: function(context) {
                                return `Median Expression: ${context.parsed.x.toFixed(2)} TPM`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: {
                            color: 'rgba(255, 255, 255, 0.05)',
                            drawBorder: false
                        },
                        ticks: {
                            color: '#9ca3af',
                            font: {
                                family: 'Outfit',
                                size: 10
                            }
                        }
                    },
                    y: {
                        grid: {
                            display: false
                        },
                        ticks: {
                            color: '#f3f4f6',
                            font: {
                                family: 'Outfit',
                                size: 10
                            }
                        }
                    }
                }
            }
        });
    }

    // 4. Druggability (Tractability) rendering
    function renderDruggability(druggabilityData) {
        tractabilityBadges.innerHTML = '';
        if (!druggabilityData || !druggabilityData.tractability) {
            tractabilityBadges.innerHTML = '<span class="no-data">Tractability data unavailable</span>';
            return;
        }

        const tract = druggabilityData.tractability;
        // Group by modality
        const modalities = {
            'SM': 'Small Molecule',
            'AB': 'Antibody',
            'PR': 'Protac (Degrader)',
            'OC': 'Other Clinical'
        };

        Object.keys(modalities).forEach(modKey => {
            // Find if any "Approved Drug" is true for this modality
            const isApproved = tract.some(item => item.modality === modKey && item.label === 'Approved Drug' && item.value === true);
            const isClinical = tract.some(item => item.modality === modKey && (item.label === 'Advanced Clinical' || item.label === 'Phase 1 Clinical') && item.value === true);
            
            const pill = document.createElement('span');
            pill.className = 'tract-pill';
            
            let statusIcon = 'square';
            if (isApproved) {
                pill.classList.add('active');
                statusIcon = 'shield-check';
                pill.innerHTML = `<i data-lucide="${statusIcon}"></i> ${modalities[modKey]}: Approved`;
            } else if (isClinical) {
                pill.classList.add('active');
                statusIcon = 'activity';
                pill.innerHTML = `<i data-lucide="${statusIcon}"></i> ${modalities[modKey]}: In Trials`;
            } else {
                pill.innerHTML = `<i data-lucide="${statusIcon}" style="color:var(--text-muted);"></i> ${modalities[modKey]}: No Evidence`;
            }
            
            tractabilityBadges.appendChild(pill);
        });
        lucide.createIcons();
    }

    // Approved & Investigational Drugs Table
    function renderApprovedDrugs(mechanisms) {
        approvedDrugsList.innerHTML = '';
        if (!mechanisms || mechanisms.length === 0) {
            approvedDrugsList.innerHTML = `<tr><td colspan="4" class="no-data">No approved targeting drugs found.</td></tr>`;
            return;
        }

        mechanisms.forEach(m => {
            const tr = document.createElement('tr');
            
            const details = m.drug_details || {};
            const phase = details.max_phase ? `Phase ${details.max_phase}` : 'Unknown';
            const action = m.action_type || m.mechanism_of_action || 'N/A';
            const type = details.molecule_type || 'Small Molecule';
            
            tr.innerHTML = `
                <td style="font-weight:600; color: var(--text-primary);">${details.pref_name || m.molecule_chembl_id}</td>
                <td>${type}</td>
                <td><span class="trial-phase-badge ${details.max_phase === 4 ? 'phase-3' : 'phase-1'}">${phase}</span></td>
                <td>${action}</td>
            `;
            approvedDrugsList.appendChild(tr);
        });
    }

    // Binding Affinities Table
    function renderBindingAffinities(activities) {
        bindingAffinitiesList.innerHTML = '';
        if (!activities || activities.length === 0) {
            bindingAffinitiesList.innerHTML = `<tr><td colspan="5" class="no-data">No bioactivity assays reported.</td></tr>`;
            return;
        }

        activities.forEach(a => {
            const tr = document.createElement('tr');
            
            const val = a.standard_value ? parseFloat(a.standard_value).toFixed(2) : 'N/A';
            const normVal = a.normalized_value_nM ? parseFloat(a.normalized_value_nM).toFixed(2) : 'N/A';
            const ref = a.document_chembl_id || 'N/A';
            
            tr.innerHTML = `
                <td style="font-family: var(--font-mono); font-size:12px;">${a.assay_chembl_id}</td>
                <td>${a.standard_type || 'IC50'}</td>
                <td>${val} ${a.standard_units || ''}</td>
                <td style="font-weight:600; color: var(--neon-blue);">${normVal} nM</td>
                <td><a href="https://www.ebi.ac.uk/chembl/document_report_card/${ref}/" target="_blank" style="color: var(--neon-purple); text-decoration: none;">${ref} <i data-lucide="external-link" style="width:10px; height:10px; display:inline;"></i></a></td>
            `;
            bindingAffinitiesList.appendChild(tr);
        });
        lucide.createIcons();
    }

    // 5. Clinical Trials Map & Recruiting List
    function renderClinicalTrials(trials) {
        // Reset Trials List
        trialsList.innerHTML = '';
        
        // Filter trials by selected Phase
        const phaseVal = phaseFilter.value;
        const filteredTrials = trials.filter(trial => {
            if (phaseVal === 'ALL') return true;
            return (trial.phase || '').toUpperCase().replace(/ /g, '') === phaseVal;
        });

        // Initialize Map if not done
        if (!leafletMapInstance) {
            leafletMapInstance = L.map('trials-map').setView([20, 0], 2);
            L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
                subdomains: 'abcd',
                maxZoom: 20
            }).addTo(leafletMapInstance);
            
            mapMarkersGroup = L.featureGroup().addTo(leafletMapInstance);
        } else {
            // Clear existing markers
            mapMarkersGroup.clearLayers();
        }

        if (filteredTrials.length === 0) {
            trialsList.innerHTML = '<div class="no-data">No active recruiting trials match filters.</div>';
            return;
        }

        const mapMarkers = [];

        filteredTrials.forEach((trial, index) => {
            // 1. Append to Scrollable List
            const item = document.createElement('div');
            item.className = 'trial-item';
            item.setAttribute('data-nct', trial.nct_id);
            
            const phaseClass = (trial.phase || '').toLowerCase().replace(/ /g, '-');
            
            item.innerHTML = `
                <div class="trial-meta-row">
                    <span class="trial-nct">${trial.nct_id}</span>
                    <span class="trial-phase-badge ${phaseClass}">${trial.phase || 'N/A'}</span>
                </div>
                <div class="trial-title">${trial.title}</div>
                <div class="trial-sponsor">${trial.sponsor}</div>
            `;
            
            // Add click listener: center map and open popup
            item.addEventListener('click', () => {
                // Highlight item
                document.querySelectorAll('.trial-item').forEach(el => el.classList.remove('active'));
                item.classList.add('active');
                
                // Find markers for this trial
                const trialMarkers = mapMarkers.filter(m => m.nctId === trial.nct_id);
                if (trialMarkers.length > 0) {
                    const firstMarker = trialMarkers[0].marker;
                    leafletMapInstance.setView(firstMarker.getLatLng(), 8);
                    firstMarker.openPopup();
                } else {
                    alert(`No mapping coordinates available for trial ${trial.nct_id}`);
                }
            });
            
            trialsList.appendChild(item);

            // 2. Add Location Markers to Map
            const locations = trial.locations || [];
            locations.forEach(loc => {
                if (loc.lat !== null && loc.lon !== null) {
                    const popupHtml = `
                        <div class="popup-trial-title">${trial.title}</div>
                        <div class="popup-trial-meta">${trial.nct_id} | ${trial.phase || 'N/A'}</div>
                        <div class="popup-trial-loc"><b>Facility:</b> ${loc.facility}</div>
                        <div class="popup-trial-loc"><b>Location:</b> ${loc.city}, ${loc.country}</div>
                    `;
                    
                    const marker = L.marker([loc.lat, loc.lon]).bindPopup(popupHtml);
                    mapMarkersGroup.addLayer(marker);
                    
                    mapMarkers.push({
                        nctId: trial.nct_id,
                        marker: marker
                    });
                }
            });
        });

        // Zoom map to fit markers
        if (mapMarkers.length > 0) {
            setTimeout(() => {
                leafletMapInstance.invalidateSize();
                leafletMapInstance.fitBounds(mapMarkersGroup.getBounds(), { padding: [30, 30] });
            }, 200);
        }
    }

    // 6. Macromolecular 3D Structure Card rendering using 3Dmol.js
    function renderProteinStructure(proteinData) {
        const nameEl = document.getElementById('protein-name');
        const uniprotEl = document.getElementById('protein-uniprot');
        const modelSelect = document.getElementById('viewer-model');
        const styleSelect = document.getElementById('viewer-style');
        const colorSelect = document.getElementById('viewer-color');
        
        if (!proteinData) {
            nameEl.textContent = 'Unavailable';
            uniprotEl.textContent = 'N/A';
            uniprotEl.href = '#';
            modelSelect.innerHTML = '<option value="alphafold">N/A</option>';
            document.getElementById('mol-viewer').innerHTML = '<div class="no-data">Protein structure data unavailable for this query.</div>';
            return;
        }

        // Set metadata
        nameEl.textContent = proteinData.full_name || 'Unknown Protein';
        uniprotEl.textContent = proteinData.accession;
        uniprotEl.href = `https://www.uniprot.org/uniprotkb/${proteinData.accession}/entry`;

        // Populate models dropdown
        modelSelect.innerHTML = `<option value="alphafold">AlphaFold (Computed)</option>`;
        const pdbs = proteinData.pdb_ids || [];
        pdbs.forEach(pdb => {
            const opt = document.createElement('option');
            opt.value = pdb.id;
            opt.textContent = `${pdb.id} (${pdb.method} - ${pdb.resolution})`;
            modelSelect.appendChild(opt);
        });

        // Initialize 3Dmol viewer if not done
        if (!molViewerInstance) {
            molViewerInstance = $3Dmol.createViewer(document.getElementById('mol-viewer'), {
                defaultcolors: $3Dmol.rasmolElementColors
            });
        }

        // Function to load and style the selected structure
        function updateModel() {
            if (!molViewerInstance) return;
            molViewerInstance.clear();
            
            const modelVal = modelSelect.value;
            const styleVal = styleSelect.value;
            const colorVal = colorSelect.value;
            
            let downloadUrl = '';
            if (modelVal === 'alphafold') {
                downloadUrl = `url:https://alphafold.ebi.ac.uk/files/AF-${proteinData.accession}-F1-model_v4.pdb`;
            } else {
                downloadUrl = `pdb:${modelVal}`;
            }

            $3Dmol.download(downloadUrl, molViewerInstance, {}, function() {
                // Apply Styles
                const styleObj = {};
                let colorScheme = colorVal;
                if (colorVal === 'ss') {
                    colorScheme = 'secondaryStructure';
                }
                styleObj[styleVal] = { colorscheme: colorScheme };
                
                molViewerInstance.setStyle({}, styleObj);
                molViewerInstance.zoomTo();
                molViewerInstance.render();
                molViewerInstance.spin(true);
            });
        }

        // Add event listeners (remove old ones if any)
        modelSelect.onchange = updateModel;
        styleSelect.onchange = updateModel;
        colorSelect.onchange = updateModel;

        // Initial render
        updateModel();
        
        // Trigger resize handling to ensure WebGL canvas sizes properly
        setTimeout(() => {
            if (molViewerInstance) {
                molViewerInstance.resize();
            }
        }, 300);
    }
});
