/* ============================================
   Dashboard — Website-Konfigurator JS
   State management, step navigation, dynamic forms,
   API integration with Google Sheets backend
   ============================================ */
(function () {
    'use strict';

    /* ---------- Template config ---------- */
    const TEMPLATE_KEYS = ['earlydog', 'bia', 'liveblocks', 'loveseen'];

    const TEMPLATE_CONFIG = {
        earlydog: { label: 'EarlyDog', desc: 'Verspielt & modern', tags: ['Handwerker', 'Coiffeure', 'Reinigungen'] },
        bia: { label: 'BiA', desc: 'Premium & editorial', tags: ['Agenturen', 'Architekten', 'Berater', 'Anw\u00e4lte'] },
        liveblocks: { label: 'Liveblocks', desc: 'Modern & technisch', tags: ['IT-Firmen', 'Startups', 'Tech'] },
        loveseen: { label: 'LoveSeen', desc: 'Luxuri\u00f6s & editorial', tags: ['Beauty', 'Wellness', 'Fotografen'] },
    };

    /* ---------- Fallback preview URLs (API now always returns real preview URLs) ---------- */
    var fallbackPreviewUrls = {
        earlydog: '/api/preview/_fallback/earlydog',
        bia: '/api/preview/_fallback/bia',
        liveblocks: '/api/preview/_fallback/liveblocks',
        loveseen: '/api/preview/_fallback/loveseen',
    };

    /* ---------- State ---------- */
    const state = {
        currentStep: 1,
        direction: 'forward',
        leadId: '',
        leadData: null,         // API response from /api/lead/<id>
        template: null,
        customizations: {
            description: '',
            values: '',
        },
        domain: null,
        domainSuggestions: [],
        agreedToTerms: false,
        logoFile: null,         // File object from upload
        imageFiles: [],         // File objects from upload
        tempLogoUrl: '',        // Cached temp URL after upload
        tempImageUrls: [],      // Cached temp URLs after upload
    };

    /* ---------- DOM refs ---------- */
    const steps = [];
    const progressSteps = [];
    let generatingOverlay, successScreen;

    /* ---------- API helpers ---------- */
    async function apiGet(path) {
        var res = await fetch('/api' + path);
        var data = await res.json();
        if (!res.ok) throw new Error(data.error || 'API-Fehler');
        return data;
    }

    async function apiPostOrder(leadId, formData) {
        var res = await fetch('/api/lead/' + leadId + '/order', {
            method: 'POST',
            body: formData,
        });
        var data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Bestellung fehlgeschlagen');
        return data;
    }

    /* ---------- Init ---------- */
    function init() {
        for (let i = 1; i <= 5; i++) {
            steps[i] = document.getElementById('step-' + i);
            progressSteps[i] = document.getElementById('pstep-' + i);
        }
        generatingOverlay = document.getElementById('generating');
        successScreen = document.getElementById('success');

        // Step 1: Lead ID — async submit
        document.getElementById('leadForm').addEventListener('submit', async function (e) {
            e.preventDefault();
            if (await validateAndFetchLead()) {
                updateTemplateIframes();
                goToStep(2);
            }
        });

        // Step 2: Template selection (single click = select, double click = select & continue)
        document.querySelectorAll('.db-tpl-card').forEach(function (card) {
            card.addEventListener('click', function () { selectTemplate(card.dataset.tpl); });
            card.addEventListener('dblclick', function () {
                selectTemplate(card.dataset.tpl);
                onStep2Next();
            });
            card.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectTemplate(card.dataset.tpl); }
            });
        });

        // Step 5: AGB checkbox
        var agbCheck = document.getElementById('agbCheck');
        if (agbCheck) {
            agbCheck.addEventListener('change', function () {
                state.agreedToTerms = agbCheck.checked;
                document.getElementById('orderBtn').disabled = !agbCheck.checked;
            });
        }

        // Order button
        var orderBtn = document.getElementById('orderBtn');
        if (orderBtn) {
            orderBtn.addEventListener('click', handleOrder);
        }

        updateProgress();
    }

    /* ---------- Step navigation ---------- */
    var highestStepReached = 1;

    function goToStep(n) {
        if (n < 1 || n > 5) return;
        if (n > highestStepReached) highestStepReached = n;
        var current = steps[state.currentStep];
        var next = steps[n];
        state.direction = n > state.currentStep ? 'forward' : 'backward';

        current.classList.add('exiting');
        setTimeout(function () {
            current.classList.remove('active', 'exiting');
            next.style.animation = 'none'; // reset
            next.offsetHeight; // reflow
            next.style.animation = '';
            next.classList.add('active');

            if (state.direction === 'backward') {
                next.style.animationName = 'stepInReverse';
            }

            state.currentStep = n;
            updateProgress();
            window.scrollTo({ top: 0, behavior: 'smooth' });

            // Re-scale iframes when step 2 becomes visible
            if (n === 2) setTimeout(scaleIframes, 50);
        }, 280);
    }

    function updateProgress() {
        for (var i = 1; i <= 5; i++) {
            var el = progressSteps[i];
            if (!el) continue;
            el.classList.remove('active', 'done');
            if (i < state.currentStep) el.classList.add('done');
            else if (i === state.currentStep) el.classList.add('active');
        }
    }

    /* ---------- Step 1: Lead ID Validation + API Fetch ---------- */
    async function validateAndFetchLead() {
        var input = document.getElementById('leadIdInput');
        var error = document.getElementById('leadIdError');
        var btn = input.closest('form').querySelector('button[type="submit"]');
        var val = input.value.trim().toLowerCase();

        input.classList.remove('error');
        error.classList.remove('visible');

        if (!val) {
            showInputError(input, error, 'Bitte gib deinen Code ein.');
            return false;
        }

        // Accept 12-char hex MD5 hash
        if (!/^[a-f0-9]{12}$/.test(val)) {
            showInputError(input, error, 'Ung\u00fcltiges Format. Pr\u00fcfe die E-Mail mit deinem Code.');
            return false;
        }

        // Show loading state
        var originalText = btn.innerHTML;
        btn.disabled = true;
        btn.textContent = 'Laden\u2026';

        try {
            var data = await apiGet('/lead/' + val);
            state.leadId = val;
            state.leadData = data;

            // Populate domain suggestions from API
            if (data.domains && data.domains.length) {
                state.domainSuggestions = data.domains.map(function (d) {
                    return {
                        domain: d.domain,
                        tld: d.tld || ('.' + d.domain.split('.').pop()),
                        available: d.available !== false,
                    };
                });
            }

            return true;
        } catch (err) {
            showInputError(input, error, err.message || 'Fehler beim Laden. Versuche es erneut.');
            return false;
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }

    function showInputError(input, errorEl, msg) {
        input.classList.add('error');
        errorEl.textContent = msg;
        errorEl.classList.add('visible');
        // Re-trigger shake
        input.style.animation = 'none';
        input.offsetHeight;
        input.style.animation = '';
    }

    /* ---------- Step 2: Template selection ---------- */
    function updateTemplateIframes(onlySelected) {
        if (!state.leadData || !state.leadData.previews) return;
        var cards = document.querySelectorAll('.db-tpl-card');

        cards.forEach(function (card, i) {
            // If onlySelected, only update the chosen template
            if (onlySelected && card.dataset.tpl !== state.template) return;

            var url = state.leadData.previews[i];
            if (!url) return;

            // Append customization params if available
            var params = new URLSearchParams();
            if (state.customizations.description) params.set('description', state.customizations.description);
            if (state.customizations.values) params.set('values', state.customizations.values);
            if (state.tempLogoUrl) params.set('logo', state.tempLogoUrl);
            state.tempImageUrls.forEach(function (u) { params.append('img', u); });

            var sep = url.includes('?') ? '&' : '?';
            var fullUrl = params.toString() ? url + sep + params.toString() : url;

            var iframe = card.querySelector('.db-preview-iframe');
            if (iframe) iframe.src = fullUrl;
        });
    }

    function selectTemplate(tplKey) {
        if (!TEMPLATE_CONFIG[tplKey]) return;
        state.template = tplKey;

        document.querySelectorAll('.db-tpl-card').forEach(function (c) {
            c.classList.toggle('selected', c.dataset.tpl === tplKey);
        });

        document.getElementById('step2NextBtn').disabled = false;
    }

    function onStep2Next() {
        if (!state.template) return;
        renderCustomizationForm();
        goToStep(3);
    }

    /* ---------- Step 3: Simplified form ---------- */
    function renderCustomizationForm() {
        var cfg = TEMPLATE_CONFIG[state.template];
        var container = document.getElementById('customFormBody');
        var badge = document.getElementById('templateBadge');

        badge.textContent = cfg.label + ' \u2014 ' + cfg.desc;

        var html = '';

        // Description — the AI figures out the rest
        html += '<div class="db-input-group">';
        html += '<label class="db-label" for="f_description">BESCHREIBE DEIN BUSINESS</label>';
        html += '<p class="db-field-hint">Was macht dein Unternehmen? Die KI erstellt daraus alle Texte f\u00fcr deine Website.</p>';
        html += '<textarea class="db-input db-textarea" id="f_description" name="description" rows="5" placeholder="z.B. Wir sind ein Malergesch\u00e4ft in Z\u00fcrich, spezialisiert auf Fassaden und Innenr\u00e4ume. Seit 20 Jahren bieten wir hochwertige Arbeit f\u00fcr Privatkunden und Unternehmen. Unser Team besteht aus 8 erfahrenen Malern."></textarea>';
        html += '</div>';

        // Values
        html += '<div class="db-input-group">';
        html += '<label class="db-label" for="f_values">WERTE & BESONDERHEITEN</label>';
        html += '<p class="db-field-hint">Was macht dich besonders? Die KI nutzt das f\u00fcr Slogans, Statistiken und Highlights.</p>';
        html += '<textarea class="db-input db-textarea" id="f_values" name="values" rows="3" placeholder="z.B. 20 Jahre Erfahrung, 500+ zufriedene Kunden, Familienunternehmen, kostenlose Beratung"></textarea>';
        html += '</div>';

        // Logo upload
        html += '<div class="db-input-group">';
        html += '<label class="db-label">LOGO</label>';
        html += '<label class="db-file-upload" id="fileLabel_logo">';
        html += '<input type="file" accept="image/*" style="display:none" onchange="window.__fileChanged(this,\'logo\')">';
        html += 'Datei ausw\u00e4hlen\u2026';
        html += '</label>';
        html += '</div>';

        // General images
        html += '<div class="db-input-group">';
        html += '<label class="db-label">BILDER</label>';
        html += '<p class="db-field-hint">Lade Fotos hoch (Team, Gesch\u00e4ft, Projekte). Die KI entscheidet, welche wo am besten passen.</p>';
        html += '<label class="db-file-upload" id="fileLabel_images">';
        html += '<input type="file" accept="image/*" multiple style="display:none" onchange="window.__fileChanged(this,\'images\')">';
        html += 'Bilder ausw\u00e4hlen\u2026';
        html += '</label>';
        html += '</div>';

        container.innerHTML = html;
    }

    // File upload label update + store file references in state
    window.__fileChanged = function (input, key) {
        var label = document.getElementById('fileLabel_' + key);
        if (input.files.length) {
            label.classList.add('has-file');
            var text = input.files.length === 1 ? input.files[0].name : input.files.length + ' Dateien ausgew\u00e4hlt';
            label.childNodes[label.childNodes.length - 1].textContent = ' ' + text;

            // Store file references for order submission
            if (key === 'logo') {
                state.logoFile = input.files[0];
                state.tempLogoUrl = '';  // Reset cached URL so re-upload happens
            } else if (key === 'images') {
                state.imageFiles = Array.from(input.files);
                state.tempImageUrls = [];  // Reset cached URLs so re-upload happens
            }
        }
    };

    function collectFormData() {
        var c = state.customizations;
        c.description = getVal('description');
        c.values = getVal('values');
    }

    function getVal(name) {
        var el = document.getElementById('f_' + name);
        return el ? el.value.trim() : '';
    }

    function hasAnyCustomization() {
        var c = state.customizations;
        return !!(c.description || c.values);
    }

    async function uploadTempFiles() {
        if (!state.logoFile && !state.imageFiles.length) return;
        // Skip if already uploaded
        if (state.tempLogoUrl || state.tempImageUrls.length) return;
        try {
            var formData = new FormData();
            if (state.logoFile) formData.append('logo', state.logoFile);
            state.imageFiles.forEach(function (f) { formData.append('images', f); });
            var res = await fetch('/api/upload-temp', { method: 'POST', body: formData });
            var data = await res.json();
            if (data.logo) state.tempLogoUrl = data.logo;
            if (data.images && data.images.length) state.tempImageUrls = data.images;
        } catch (e) {
            console.warn('Temp file upload failed:', e);
        }
    }

    function onStep3Next() {
        collectFormData();

        // Only generate fallback suggestions if API didn't provide any
        if (!state.domainSuggestions.length) {
            generateDomainSuggestions();
        }

        if (hasAnyCustomization() || state.logoFile || state.imageFiles.length) {
            showGenerating(async function () {
                // Upload files to temp storage during the generating overlay
                await uploadTempFiles();
                // Refresh all template iframes with customizations + uploaded files
                updateTemplateIframes();
                renderDomainCards();
                goToStep(4);
            });
        } else {
            renderDomainCards();
            goToStep(4);
        }
    }

    /* ---------- Generating overlay ---------- */
    function showGenerating(callback) {
        generatingOverlay.classList.add('visible');
        setTimeout(function () {
            generatingOverlay.classList.remove('visible');
            if (callback) callback();
        }, 3500);
    }

    /* ---------- Step 4: Domain suggestions ---------- */
    function generateDomainSuggestions() {
        // Fallback: generate from business name or use placeholder
        var name = (state.leadData && state.leadData.business_name) || 'meinbusiness';
        var clean = name.toLowerCase()
            .replace(/\u00e4/g, 'ae').replace(/\u00f6/g, 'oe').replace(/\u00fc/g, 'ue')
            .replace(/\u00e9|\u00e8|\u00ea/g, 'e')
            .replace(/[^a-z0-9]/g, '')
            .substring(0, 30);

        if (!clean) clean = 'meinbusiness';

        var suggestions = [
            { domain: clean + '.ch', tld: '.ch', available: true },
            { domain: clean + '.com', tld: '.com', available: true },
            { domain: clean + '-online.ch', tld: '.ch', available: true },
        ];

        state.domainSuggestions = suggestions;
    }

    function renderDomainCards() {
        var list = document.getElementById('domainList');
        var html = '';

        state.domainSuggestions.forEach(function (d, i) {
            html += '<div class="db-domain-card" data-domain-idx="' + i + '" tabindex="0">';
            html += '<div class="db-radio"><div class="db-radio-dot"></div></div>';
            html += '<div class="db-domain-info">';
            html += '<div class="db-domain-name">' + d.domain + '</div>';
            html += '<div class="db-domain-meta">';
            html += '<span class="db-tld-badge">' + d.tld + '</span>';
            html += '<span class="db-avail"><span class="db-avail-dot' + (d.available ? ' available' : '') + '"></span>' + (d.available ? 'Verf\u00fcgbar' : 'Nicht verf\u00fcgbar') + '</span>';
            html += '</div></div>';
            html += '</div>';
        });

        list.innerHTML = html;

        // Bind click events
        list.querySelectorAll('.db-domain-card').forEach(function (card) {
            card.addEventListener('click', function () { selectDomain(parseInt(card.dataset.domainIdx)); });
            card.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectDomain(parseInt(card.dataset.domainIdx)); }
            });
        });
    }

    function selectDomain(idx) {
        state.domain = state.domainSuggestions[idx].domain;
        document.querySelectorAll('.db-domain-card').forEach(function (c, i) {
            c.classList.toggle('selected', i === idx);
        });
        document.getElementById('step4NextBtn').disabled = false;
    }

    /* ---------- Step 5: Review ---------- */
    function renderReview() {
        // Domain / web address
        document.getElementById('reviewDomain').textContent = state.domain || '\u2014';
    }

    async function openPreview() {
        // Get base preview URL from API data
        var url = '';
        if (state.leadData && state.leadData.previews) {
            var idx = TEMPLATE_KEYS.indexOf(state.template);
            if (idx >= 0) url = state.leadData.previews[idx];
        }
        if (!url) url = fallbackPreviewUrls[state.template] || '#';

        // Build query params with customizations from Step 3
        var params = new URLSearchParams();
        if (state.customizations.description) params.set('description', state.customizations.description);
        if (state.customizations.values) params.set('values', state.customizations.values);

        // Upload files if not already cached
        await uploadTempFiles();

        // Use cached temp URLs
        if (state.tempLogoUrl) params.set('logo', state.tempLogoUrl);
        state.tempImageUrls.forEach(function (u) { params.append('img', u); });

        var sep = url.includes('?') ? '&' : '?';
        var fullUrl = params.toString() ? url + sep + params.toString() : url;

        var overlay = document.getElementById('previewOverlay');
        var iframe = document.getElementById('previewOverlayIframe');
        var loading = document.getElementById('previewLoading');

        // Show loading indicator
        loading.classList.remove('hidden');
        iframe.onload = function () { loading.classList.add('hidden'); };

        iframe.src = fullUrl;
        overlay.classList.add('visible');
    }

    function closePreview() {
        var overlay = document.getElementById('previewOverlay');
        var iframe = document.getElementById('previewOverlayIframe');
        var loading = document.getElementById('previewLoading');
        overlay.classList.remove('visible');
        iframe.src = 'about:blank';
        loading.classList.remove('hidden');
    }

    function onStep5() {
        renderReview();
        goToStep(5);
    }

    /* ---------- Order ---------- */
    async function handleOrder() {
        if (!state.agreedToTerms) return;

        var orderBtn = document.getElementById('orderBtn');
        var originalText = orderBtn.innerHTML;
        orderBtn.disabled = true;
        orderBtn.textContent = 'Wird gesendet\u2026';

        // Build FormData for multipart upload
        var formData = new FormData();
        formData.append('chosen_template', state.template || '');
        formData.append('description', state.customizations.description || '');
        formData.append('values', state.customizations.values || '');
        formData.append('selected_domain', state.domain || '');
        formData.append('agreed_to_terms', 'true');

        // Attach files
        if (state.logoFile) {
            formData.append('logo', state.logoFile);
        }
        state.imageFiles.forEach(function (f) {
            formData.append('images', f);
        });

        try {
            await apiPostOrder(state.leadId, formData);

            // Success — show success screen
            steps[5].classList.remove('active');
            successScreen.classList.add('active');
            document.querySelector('.db-progress').style.display = 'none';
        } catch (err) {
            // Show error and re-enable button
            alert('Fehler: ' + err.message);
            orderBtn.disabled = false;
            orderBtn.innerHTML = originalText;
        }
    }

    /* ---------- Step navigation via progress dots ---------- */
    function navStep(n) {
        // Can only navigate to steps already visited (done) or current
        if (n > highestStepReached || n === state.currentStep) return;
        // If going to step 2, refresh iframes with latest customizations
        if (n === 2) setTimeout(function () { updateTemplateIframes(); }, 50);
        // If going to step 3, re-render form if template selected
        if (n === 3 && state.template) renderCustomizationForm();
        // If going to step 4, re-render domain cards
        if (n === 4 && state.domainSuggestions.length) renderDomainCards();
        // If going to step 5, re-render review
        if (n === 5) renderReview();
        goToStep(n);
    }

    /* ---------- Iframe scaling ---------- */
    function scaleIframes() {
        document.querySelectorAll('.db-preview-scaler').forEach(function (scaler) {
            var w = scaler.offsetWidth;
            if (w <= 0) return;
            var iframe = scaler.querySelector('.db-preview-iframe');
            if (!iframe) return;
            var scale = w / 1440;
            iframe.style.transform = 'scale(' + scale + ')';
        });
    }

    /* ---------- Expose to HTML onclick ---------- */
    window.dbGoBack = function (n) { goToStep(n); };
    window.dbStep2Next = onStep2Next;
    window.dbStep3Next = onStep3Next;
    window.dbStep4Next = onStep5;
    window.dbGoHome = function () { window.location.href = 'index.html'; };
    window.dbNavStep = function (n) { navStep(n); };
    window.dbOpenPreview = openPreview;
    window.dbClosePreview = closePreview;

    /* ---------- Start ---------- */
    document.addEventListener('DOMContentLoaded', function () {
        init();
        // Scale iframes once loaded
        scaleIframes();
        window.addEventListener('resize', scaleIframes);
        // Re-scale after short delay for iframe load
        setTimeout(scaleIframes, 500);
    });
})();
