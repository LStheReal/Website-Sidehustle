/* ============================================
   Dashboard — Website-Konfigurator JS
   6-step flow: Start → Info → Design → Vorschau → Adresse → Bestellen
   State management, step navigation, dynamic forms,
   AI chat editor, background generation polling,
   progress saving & returning user support
   ============================================ */
(function () {
    'use strict';

    /* ---------- Template config ---------- */
    const TEMPLATE_KEYS = ['earlydog', 'bia', 'liveblocks', 'loveseen'];
    const TOTAL_STEPS = 6;

    const TEMPLATE_CONFIG = {
        earlydog: { label: 'Verspielt & modern', tags: ['Handwerker', 'Coiffeure', 'Reinigungen'] },
        bia: { label: 'Premium & editorial', tags: ['Agenturen', 'Architekten', 'Berater', 'Anw\u00e4lte'] },
        liveblocks: { label: 'Modern & technisch', tags: ['IT-Firmen', 'Startups', 'Tech'] },
        loveseen: { label: 'Luxuri\u00f6s & editorial', tags: ['Beauty', 'Wellness', 'Fotografen'] },
    };

    /* ---------- Fallback preview URLs ---------- */
    var fallbackPreviewUrls = {
        earlydog: 'templates/earlydog/index.html',
        bia: 'templates/bia/index.html',
        liveblocks: 'templates/liveblocks/index.html',
        loveseen: 'templates/loveseen/index.html',
    };

    /* ---------- State ---------- */
    const state = {
        currentStep: 1,
        direction: 'forward',
        leadId: '',
        leadData: null,
        isNoCode: false,
        template: null,
        customizations: {
            description: '',
            values: '',
            phone: '',
            address: '',
        },
        formData: {
            business_name: '',
            description: '',
            values: '',
            phone: '',
            address: '',
        },
        domain: null,
        domainSuggestions: [],
        agreedToTerms: false,
        logoFile: null,
        imageFiles: [],
        tempLogoUrl: '',
        tempImageUrls: [],
        // New state for v2
        generationStatus: {},
        generatedUrls: {},
        chatHistory: [],
        currentEditHtml: '',
        htmlUndoStack: [],
        lastUploadedImageUrl: null,
        chatPanelOpen: false,
        generationPollTimer: null,
        hasExistingFormData: false,
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

    async function apiPost(path, body) {
        var res = await fetch('/api' + path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
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
        for (let i = 1; i <= TOTAL_STEPS; i++) {
            steps[i] = document.getElementById('step-' + i);
            progressSteps[i] = document.getElementById('pstep-' + i);
        }
        generatingOverlay = document.getElementById('generating');
        successScreen = document.getElementById('success');

        // Step 1: Lead ID — async submit (code flow)
        document.getElementById('leadForm').addEventListener('submit', async function (e) {
            e.preventDefault();
            if (await validateAndFetchLead()) {
                state.isNoCode = false;
                handlePostLogin();
            }
        });

        // Step 1: Email — async submit (no-code flow)
        document.getElementById('emailForm').addEventListener('submit', async function (e) {
            e.preventDefault();
            if (await validateAndRegisterEmail()) {
                state.isNoCode = true;
                try {
                    localStorage.setItem('db_leadId', state.leadId);
                    localStorage.setItem('db_isNoCode', '1');
                } catch(e) {}
                renderInfoForm();
                goToStep(2);
            }
        });

        // Step 3: Template selection
        document.querySelectorAll('.db-tpl-card').forEach(function (card) {
            card.addEventListener('click', function () { selectTemplate(card.dataset.tpl); });
            card.addEventListener('dblclick', function () {
                selectTemplate(card.dataset.tpl);
                onStep3Next();
            });
            card.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectTemplate(card.dataset.tpl); }
            });
        });

        // Step 4: Chat input — Enter to send, Shift+Enter for newline
        var chatInput = document.getElementById('chatInput');
        if (chatInput) {
            chatInput.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendChatMessage();
                }
            });
        }

        // Step 6: AGB checkbox
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

        // Save HTML on tab close
        window.addEventListener('beforeunload', function () {
            if (state.currentStep === 4 && state.currentEditHtml && state.template) {
                var data = JSON.stringify({ html: state.currentEditHtml, template_key: state.template });
                navigator.sendBeacon('/api/lead/' + state.leadId + '/save-html', new Blob([data], { type: 'application/json' }));
            }
        });

        updateProgress();

        // Auto-restore session from localStorage (fires after DOM is ready)
        setTimeout(tryAutoRestore, 0);
    }

    /* ---------- Session restore from localStorage ---------- */
    async function tryAutoRestore() {
        var cachedId, cachedStep, cachedIsNoCode;
        try {
            cachedId = localStorage.getItem('db_leadId');
            cachedStep = parseInt(localStorage.getItem('db_step') || '1', 10);
            cachedIsNoCode = localStorage.getItem('db_isNoCode') === '1';
        } catch(e) { return; }

        if (!cachedId) return;

        try {
            var data = await apiGet('/lead/' + cachedId);
            state.leadId = cachedId;
            state.leadData = data;
            state.isNoCode = cachedIsNoCode;

            if (data.domains && data.domains.length) {
                state.domainSuggestions = data.domains;
            }

            handlePostLogin();

            // Navigate beyond step 3 if that's where the user was
            if (cachedStep >= 4 && (state.leadData.chosen_template || state.template)) {
                var tpl = state.template || state.leadData.chosen_template;
                setTimeout(function() {
                    state.template = tpl;
                    initChatEditor();
                    goToStep(4);

                    if (cachedStep >= 5) {
                        setTimeout(async function() {
                            if (!state.domainSuggestions.length) {
                                await generateDomainSuggestions();
                            }
                            renderDomainCards();
                            goToStep(5);

                            if (cachedStep >= 6) {
                                setTimeout(function() {
                                    renderReview();
                                    goToStep(6);
                                }, 400);
                            }
                        }, 400);
                    }
                }, 400);
            }
        } catch(e) {
            // Lead not found or network error — clear stale cache, stay on step 1
            try {
                localStorage.removeItem('db_leadId');
                localStorage.removeItem('db_step');
                localStorage.removeItem('db_isNoCode');
            } catch(e2) {}
        }
    }

    /* ---------- Post-login routing ---------- */
    function handlePostLogin() {
        // Persist session for reload recovery
        try {
            localStorage.setItem('db_leadId', state.leadId);
            localStorage.setItem('db_isNoCode', state.isNoCode ? '1' : '0');
        } catch(e) {}

        var d = state.leadData;

        // Check for existing form data (returning user)
        if (d.form_description || d.form_values) {
            state.hasExistingFormData = true;
            state.formData = {
                business_name: d.form_business_name || d.business_name || '',
                description: d.form_description || '',
                values: d.form_values || '',
                phone: d.form_phone || d.phone || '',
                address: d.form_address || d.address || '',
            };
            state.customizations.description = state.formData.description;
            state.customizations.values = state.formData.values;
            state.customizations.phone = state.formData.phone;
            state.customizations.address = state.formData.address;
        }

        // Check for existing generated URLs
        TEMPLATE_KEYS.forEach(function (k) {
            if (d['url_' + k]) state.generatedUrls[k] = d['url_' + k];
        });

        // Check generation status
        if (d.generation_status) {
            try { state.generationStatus = JSON.parse(d.generation_status); } catch (e) {}
        }

        if (state.hasExistingFormData) {
            // Returning user — skip to Design step
            initTemplateStep();
            goToStep(3);

            // Check if generation is still running
            var hasAllDone = TEMPLATE_KEYS.every(function (k) {
                return state.generationStatus[k] === 'done' || state.generationStatus[k] === 'error';
            });
            if (!hasAllDone && Object.keys(state.generationStatus).length > 0) {
                startGenerationPolling();
            }
        } else {
            // New code user — go to info form
            renderInfoForm();
            goToStep(2);
        }
    }

    /* ---------- Step navigation ---------- */
    var highestStepReached = 1;

    function goToStep(n) {
        if (n < 1 || n > TOTAL_STEPS) return;
        if (n > highestStepReached) highestStepReached = n;
        var current = steps[state.currentStep];
        var next = steps[n];
        state.direction = n > state.currentStep ? 'forward' : 'backward';

        current.classList.add('exiting');
        setTimeout(function () {
            current.classList.remove('active', 'exiting');
            next.style.animation = 'none';
            next.offsetHeight;
            next.style.animation = '';
            next.classList.add('active');

            if (state.direction === 'backward') {
                next.style.animationName = 'stepInReverse';
            }

            state.currentStep = n;
            try { if (state.leadId) localStorage.setItem('db_step', String(n)); } catch(e) {}
            updateProgress();
            window.scrollTo({ top: 0, behavior: 'smooth' });

            // Re-scale iframes when step 3 becomes visible
            if (n === 3) setTimeout(scaleIframes, 50);
        }, 280);
    }

    function updateProgress() {
        for (var i = 1; i <= TOTAL_STEPS; i++) {
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

        if (!/^[a-f0-9]{12}$/.test(val)) {
            showInputError(input, error, 'Ung\u00fcltiges Format. Pr\u00fcfe die E-Mail mit deinem Code.');
            return false;
        }

        var originalText = btn.innerHTML;
        btn.disabled = true;
        btn.textContent = 'Laden\u2026';

        try {
            var data = await apiGet('/lead/' + val);
            state.leadId = val;
            state.leadData = data;

            if (data.domains && data.domains.length) {
                state.domainSuggestions = data.domains.map(function (d) {
                    return { domain: d.domain, tld: d.tld || ('.' + d.domain.split('.').pop()), available: d.available !== false };
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

    /* ---------- Step 1: Email Registration (no-code flow) ---------- */
    async function validateAndRegisterEmail() {
        var input = document.getElementById('emailInput');
        var error = document.getElementById('emailError');
        var btn = input.closest('form').querySelector('button[type="submit"]');
        var val = input.value.trim().toLowerCase();

        input.classList.remove('error');
        error.classList.remove('visible');

        if (!val) {
            showInputError(input, error, 'Bitte gib deine E-Mail-Adresse ein.');
            return false;
        }

        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val)) {
            showInputError(input, error, 'Bitte gib eine g\u00fcltige E-Mail-Adresse ein.');
            return false;
        }

        var originalText = btn.innerHTML;
        btn.disabled = true;
        btn.textContent = 'Laden\u2026';

        try {
            var data = await apiPost('/lead/register', { email: val });
            state.leadId = data.lead_id;
            state.leadData = data;
            state.domainSuggestions = [];
            return true;
        } catch (err) {
            showInputError(input, error, err.message || 'Fehler beim Registrieren. Versuche es erneut.');
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
        input.style.animation = 'none';
        input.offsetHeight;
        input.style.animation = '';
    }

    /* ---------- Step 2: Info Giving Form ---------- */
    function renderInfoForm() {
        var container = document.getElementById('infoFormBody');
        if (!container) return;

        var html = '';
        var isRequired = state.isNoCode;
        var reqLabel = isRequired ? ' <span style="color:var(--red);">*</span>' : '';
        var reqAttr = isRequired ? ' required' : '';
        var fd = state.formData;

        // Info banner
        html += '<div style="background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.2);border-radius:12px;padding:14px 18px;margin-bottom:20px;display:flex;align-items:flex-start;gap:10px;">';
        html += '<span style="font-size:20px;line-height:1;">💡</span>';
        html += '<span style="font-size:14px;color:var(--text-secondary);line-height:1.5;">Je mehr du hier schreibst, desto besser und persönlicher wird deine Website. Beschreibe dein Business so detailliert wie möglich.</span>';
        html += '</div>';

        // Business name (only for no-code users)
        if (state.isNoCode) {
            html += '<div class="db-input-group">';
            html += '<label class="db-label" for="f_business_name">FIRMENNAME <span style="color:var(--red);">*</span></label>';
            html += '<p class="db-field-hint">Der Name deines Unternehmens, wie er auf der Website erscheinen soll.</p>';
            html += '<input class="db-input" type="text" id="f_business_name" name="business_name" placeholder="z.B. Maler Meier AG" value="' + escAttr(fd.business_name) + '" required>';
            html += '</div>';
        }

        // Description
        html += '<div class="db-input-group">';
        html += '<label class="db-label" for="f_description">BESCHREIBE DEIN BUSINESS' + reqLabel + '</label>';
        html += '<p class="db-field-hint">Beschreibe was du anbietest, wer deine Kunden sind und was dich auszeichnet. Je detaillierter, desto pers\u00f6nlicher wird deine Website.</p>';
        html += '<textarea class="db-input db-textarea" id="f_description" name="description" rows="5" placeholder="z.B. Wir sind ein Malergesch\u00e4ft in Z\u00fcrich, spezialisiert auf Fassaden und Innenr\u00e4ume. Seit 20 Jahren bieten wir hochwertige Arbeit f\u00fcr Privatkunden und Unternehmen."' + reqAttr + '>' + escHtml(fd.description) + '</textarea>';
        html += '</div>';

        // Values
        html += '<div class="db-input-group">';
        html += '<label class="db-label" for="f_values">WERTE & BESONDERHEITEN' + reqLabel + '</label>';
        html += '<p class="db-field-hint">Nenne konkrete Zahlen, Erfahrung und Besonderheiten. Diese erscheinen als Highlights auf deiner Website.</p>';
        html += '<textarea class="db-input db-textarea" id="f_values" name="values" rows="3" placeholder="z.B. 20 Jahre Erfahrung, 500+ zufriedene Kunden, Familienunternehmen, kostenlose Beratung"' + reqAttr + '>' + escHtml(fd.values) + '</textarea>';
        html += '</div>';

        // Contact info
        html += '<div class="db-input-group">';
        html += '<label class="db-label" for="f_phone">TELEFONNUMMER <span style="color:var(--red);">*</span></label>';
        html += '<p class="db-field-hint">Wird auf deiner Website angezeigt, damit Kunden dich erreichen k\u00f6nnen.</p>';
        html += '<input class="db-input" type="tel" id="f_phone" name="phone" placeholder="z.B. +41 44 123 45 67" value="' + escAttr(fd.phone) + '" required>';
        html += '</div>';

        html += '<div class="db-input-group">';
        html += '<label class="db-label" for="f_address">ADRESSE</label>';
        html += '<p class="db-field-hint">Firmenadresse f\u00fcr den Kontaktbereich deiner Website.</p>';
        html += '<input class="db-input" type="text" id="f_address" name="address" placeholder="z.B. Bahnhofstrasse 10, 8001 Z\u00fcrich" value="' + escAttr(fd.address) + '">';
        html += '</div>';

        // Logo upload
        html += '<div class="db-input-group">';
        html += '<label class="db-label">LOGO</label>';
        html += '<label class="db-file-upload" id="fileLabel_logo">';
        html += '<input type="file" accept="image/*" style="display:none" onchange="window.__fileChanged(this,\'logo\')">';
        html += 'Datei ausw\u00e4hlen\u2026';
        html += '</label>';
        html += '</div>';

        // Images
        html += '<div class="db-input-group">';
        html += '<label class="db-label">BILDER</label>';
        html += '<p class="db-field-hint">Lade Fotos hoch (Team, Gesch\u00e4ft, Projekte). Die KI entscheidet, welche wo am besten passen.</p>';
        html += '<div id="imageList" class="db-image-list"></div>';
        html += '<label class="db-file-upload" id="fileLabel_images">';
        html += '<input type="file" accept="image/*" multiple style="display:none" onchange="window.__fileChanged(this,\'images\')">';
        html += '+ Bilder hinzuf\u00fcgen';
        html += '</label>';
        html += '</div>';

        container.innerHTML = html;
        setTimeout(function () { renderImageList(); }, 0);

        if (state.logoFile) {
            var logoLabel = document.getElementById('fileLabel_logo');
            if (logoLabel) {
                logoLabel.classList.add('has-file');
                logoLabel.childNodes[logoLabel.childNodes.length - 1].textContent = ' ' + state.logoFile.name;
            }
        }

        if (state.hasExistingFormData) {
            var banner = document.getElementById('savedDataBanner');
            if (banner) banner.style.display = '';
        }
    }

    function escAttr(s) { return (s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;'); }
    function escHtml(s) { return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

    // File upload
    window.__fileChanged = function (input, key) {
        var label = document.getElementById('fileLabel_' + key);
        if (input.files.length) {
            if (key === 'logo') {
                state.logoFile = input.files[0];
                state.tempLogoUrl = '';
                label.classList.add('has-file');
                label.childNodes[label.childNodes.length - 1].textContent = ' ' + input.files[0].name;
            } else if (key === 'images') {
                var newFiles = Array.from(input.files);
                state.imageFiles = state.imageFiles.concat(newFiles);
                state.tempImageUrls = [];
                renderImageList();
            }
        }
    };

    function renderImageList() {
        var container = document.getElementById('imageList');
        if (!container) return;
        if (!state.imageFiles.length) { container.innerHTML = ''; return; }
        var html = '';
        state.imageFiles.forEach(function (f, i) {
            html += '<div class="db-image-item">';
            html += '<span class="db-image-name">' + escHtml(f.name) + '</span>';
            html += '<button type="button" class="db-image-remove" onclick="window.__removeImage(' + i + ')">\u00d7</button>';
            html += '</div>';
        });
        container.innerHTML = html;
    }

    window.__removeImage = function (idx) {
        state.imageFiles.splice(idx, 1);
        state.tempImageUrls = [];
        renderImageList();
    };

    function collectFormData() {
        var fd = state.formData;
        fd.description = getVal('description');
        fd.values = getVal('values');
        fd.phone = getVal('phone');
        fd.address = getVal('address');
        if (state.isNoCode) {
            fd.business_name = getVal('business_name');
            if (fd.business_name && state.leadData) {
                state.leadData.business_name = fd.business_name;
            }
        }
        state.customizations.description = fd.description;
        state.customizations.values = fd.values;
        state.customizations.phone = fd.phone;
        state.customizations.address = fd.address;
    }

    function getVal(name) {
        var el = document.getElementById('f_' + name);
        return el ? el.value.trim() : '';
    }

    async function onStep2Next() {
        collectFormData();
        var fd = state.formData;

        // Validation for no-code users
        if (state.isNoCode) {
            if (!fd.business_name) { focusError('business_name'); return; }
            if (!fd.description) { focusError('description'); return; }
            if (!fd.values) { focusError('values'); return; }
        }

        // Phone required for all users
        if (!fd.phone) { focusError('phone'); return; }

        // Save form data first — MUST complete before generation reads it
        try {
            await apiPost('/lead/' + state.leadId + '/save-form', fd);
        } catch (e) {
            console.warn('Form save failed:', e);
        }

        // Trigger background generation — pass form data directly (belt & suspenders)
        apiPost('/lead/' + state.leadId + '/generate-all', fd).catch(function (e) {
            console.warn('Generate-all trigger failed:', e);
        });

        // Go to template selection immediately (no overlay, no blocking)
        initTemplateStep();
        goToStep(3);
        startGenerationPolling();
    }

    function focusError(fieldName) {
        var el = document.getElementById('f_' + fieldName);
        if (el) { el.focus(); el.classList.add('error'); }
    }

    /* ---------- Step 3: Choose Style ---------- */
    function initTemplateStep() {
        var cards = document.querySelectorAll('.db-tpl-card');
        cards.forEach(function (card) {
            var iframe = card.querySelector('.db-preview-iframe');
            if (!iframe) return;
            var tpl = card.dataset.tpl;
            if (state.generatedUrls[tpl]) {
                iframe.src = state.generatedUrls[tpl];
                var badge = card.querySelector('.db-tpl-personalized-badge');
                if (badge) badge.style.display = '';
            } else {
                iframe.src = fallbackPreviewUrls[tpl] || ('templates/' + tpl + '/index.html');
            }
        });
    }

    function startGenerationPolling() {
        if (state.generationPollTimer) return;
        state.generationPollTimer = setInterval(pollGenerationStatus, 5000);
        pollGenerationStatus();
    }

    function stopGenerationPolling() {
        if (state.generationPollTimer) {
            clearInterval(state.generationPollTimer);
            state.generationPollTimer = null;
        }
    }

    async function pollGenerationStatus() {
        try {
            var data = await apiGet('/lead/' + state.leadId + '/generation-status');
            state.generationStatus = data.status || {};
            var urls = data.urls || {};

            for (var tpl in data.status) {
                if (data.status[tpl] === 'done' && urls[tpl]) {
                    state.generatedUrls[tpl] = urls[tpl];
                    var card = document.querySelector('.db-tpl-card[data-tpl="' + tpl + '"]');
                    if (card) {
                        var iframe = card.querySelector('.db-preview-iframe');
                        if (iframe && !iframe.src.includes(urls[tpl])) {
                            iframe.src = urls[tpl];
                        }
                        var badge = card.querySelector('.db-tpl-personalized-badge');
                        if (badge) badge.style.display = '';
                    }
                }
            }

            // If on step 4 waiting for generation, check if selected template is ready
            if (state.currentStep === 4 && state.template && data.status[state.template] === 'done' && !state.currentEditHtml) {
                if (state.logoFile || state.imageFiles.length > 0) {
                    loadPreviewWithImages();
                } else {
                    var previewUrl = '/api/preview/' + state.leadId + '/' + state.template;
                    loadEditorWithHtml(previewUrl, null);
                }
            }

            var allDone = Object.values(data.status).every(function (s) { return s === 'done' || s === 'error'; });
            if (allDone) stopGenerationPolling();
        } catch (e) {
            console.warn('Poll error:', e);
        }
    }

    function selectTemplate(tplKey) {
        if (!TEMPLATE_CONFIG[tplKey]) return;
        state.template = tplKey;

        document.querySelectorAll('.db-tpl-card').forEach(function (c) {
            c.classList.toggle('selected', c.dataset.tpl === tplKey);
        });

        document.getElementById('step3NextBtn').disabled = false;
    }

    function onStep3Next() {
        if (!state.template) return;

        apiPost('/lead/' + state.leadId + '/update', { chosen_template: state.template }).catch(function (e) {
            console.warn('Template save failed:', e);
        });

        initChatEditor();
        goToStep(4);
    }

    /* ---------- Step 4: AI Chat Editor ---------- */
    var EDITOR_STAGES = [
        { pct: 10,  text: 'Deine Website wird vorbereitet\u2026' },
        { pct: 30,  text: 'KI generiert Texte\u2026' },
        { pct: 50,  text: 'Bilder werden geladen\u2026' },
        { pct: 70,  text: 'Design wird zusammengestellt\u2026' },
        { pct: 90,  text: 'Fast fertig\u2026' },
    ];
    var editorStageIdx = 0;
    var editorStageTimer = null;

    function startEditorProgress() {
        var bar = document.getElementById('editorGenBar');
        var statusText = document.getElementById('editorStatusText');
        editorStageIdx = 0;
        if (bar) bar.style.width = EDITOR_STAGES[0].pct + '%';
        if (statusText) statusText.textContent = EDITOR_STAGES[0].text;
        if (editorStageTimer) clearInterval(editorStageTimer);
        editorStageTimer = setInterval(function () {
            editorStageIdx++;
            if (editorStageIdx < EDITOR_STAGES.length) {
                if (bar) bar.style.width = EDITOR_STAGES[editorStageIdx].pct + '%';
                if (statusText) statusText.textContent = EDITOR_STAGES[editorStageIdx].text;
            }
        }, 3000);
    }

    function stopEditorProgress() {
        if (editorStageTimer) { clearInterval(editorStageTimer); editorStageTimer = null; }
        var bar = document.getElementById('editorGenBar');
        var statusText = document.getElementById('editorStatusText');
        if (bar) bar.style.width = '100%';
        if (statusText) statusText.textContent = 'Fertig!';
    }

    async function loadPreviewWithImages() {
        var editorIframe = document.getElementById('editorIframe');
        try {
            var fd = new FormData();
            fd.append('lead_id', state.leadId);
            fd.append('template', state.template);
            fd.append('description', state.customizations.description || '');
            fd.append('values', state.customizations.values || '');
            if (state.customizations.phone) fd.append('phone', state.customizations.phone);
            if (state.customizations.address) fd.append('address', state.customizations.address);
            if (state.logoFile) fd.append('logo', state.logoFile);
            state.imageFiles.forEach(function (f) { fd.append('images', f); });

            var resp = await fetch('/api/preview-with-images', { method: 'POST', body: fd });
            if (resp.ok) {
                var html = await resp.text();
                if (html && html.length > 100) {
                    state.currentEditHtml = html;
                    editorIframe.srcdoc = html;
                    showEditorAfterLoad();
                    return;
                }
            }
        } catch (e) {
            console.warn('Preview with images failed:', e);
        }
        // Fallback to regular preview
        var previewUrl = '/api/preview/' + state.leadId + '/' + state.template;
        loadEditorWithHtml(previewUrl, null);
    }

    function initChatEditor() {
        var editorIframe = document.getElementById('editorIframe');
        var editorLoading = document.getElementById('editorLoading');
        var editorChat = document.getElementById('editorChat');
        var chatToggle = document.getElementById('chatToggle');
        var navBtns = document.querySelector('#step-4 .db-nav-btns');

        state.chatHistory = [];
        state.currentEditHtml = '';
        state.htmlUndoStack = [];
        state.lastUploadedImageUrl = null;

        state.chatHistory.push({
            role: 'assistant',
            content: 'Hallo! Sag mir einfach, was du an deiner Website \u00e4ndern m\u00f6chtest \u2014 ich setze es sofort um. Wenn du etwas Spezifischeres brauchst oder einen pers\u00f6nlichen Beratungstermin m\u00f6chtest, schreib uns einfach eine E-Mail unter info@meine-kmu.ch.',
        });
        renderChatMessages();

        // Always show loading with progress bar
        editorLoading.style.display = '';
        if (editorChat) editorChat.style.display = 'none';
        if (chatToggle) chatToggle.style.display = 'none';
        if (navBtns) navBtns.style.display = 'none';
        startEditorProgress();

        var hasFiles = (state.logoFile || state.imageFiles.length > 0);
        var deployedUrl = state.generatedUrls[state.template];

        if (hasFiles && !deployedUrl) {
            // User uploaded images/logo: POST to preview-with-images so they appear
            loadPreviewWithImages();
        } else if (deployedUrl) {
            // Returning user: try proxy for deployed URL (preserves edits), fall back to preview
            var previewUrl = '/api/preview/' + state.leadId + '/' + state.template;
            loadEditorWithHtml(deployedUrl, previewUrl);
        } else {
            // No files, first visit: use GET preview
            var previewUrl = '/api/preview/' + state.leadId + '/' + state.template;
            loadEditorWithHtml(previewUrl, null);
            if (!state.generationPollTimer) startGenerationPolling();
        }
    }

    function showEditorAfterLoad() {
        stopEditorProgress();
        setTimeout(function () {
            var editorLoading = document.getElementById('editorLoading');
            var editorChat = document.getElementById('editorChat');
            var chatToggle = document.getElementById('chatToggle');
            var navBtns = document.querySelector('#step-4 .db-nav-btns');
            if (editorLoading) { editorLoading.style.display = 'none'; editorLoading.classList.remove('fullscreen'); }
            if (editorChat) editorChat.style.display = '';
            if (chatToggle) chatToggle.style.display = '';
            if (navBtns) navBtns.style.display = '';
        }, 500);
    }

    async function loadEditorWithHtml(url, fallbackUrl) {
        var editorIframe = document.getElementById('editorIframe');

        // Try fetching the primary URL
        try {
            var resp = await fetch(url);
            if (resp.ok) {
                var html = await resp.text();
                if (html && html.length > 100) {
                    state.currentEditHtml = html;
                    editorIframe.srcdoc = html;
                    showEditorAfterLoad();
                    return;
                }
            }
        } catch (e) {
            console.warn('Primary fetch failed:', e);
        }

        // Try proxy for cross-origin deployed URLs
        if (url.includes('.pages.dev')) {
            try {
                var proxyResp = await apiPost('/fetch-url', { url: url });
                if (proxyResp && proxyResp.html && proxyResp.html.length > 100) {
                    state.currentEditHtml = proxyResp.html;
                    editorIframe.srcdoc = proxyResp.html;
                    showEditorAfterLoad();
                    return;
                }
            } catch (e) { console.warn('Proxy fetch failed:', e); }
        }

        // Try fallback URL (same-origin preview)
        if (fallbackUrl) {
            try {
                var fbResp = await fetch(fallbackUrl);
                if (fbResp.ok) {
                    var fbHtml = await fbResp.text();
                    if (fbHtml && fbHtml.length > 100) {
                        state.currentEditHtml = fbHtml;
                        editorIframe.srcdoc = fbHtml;
                        showEditorAfterLoad();
                        return;
                    }
                }
            } catch (e) { console.warn('Fallback fetch failed:', e); }
        }

        // Last resort: load URL directly in iframe
        console.warn('All fetch methods failed, loading URL directly in iframe');
        editorIframe.src = url;
        editorIframe.onload = function () { showEditorAfterLoad(); };
    }

    function renderChatMessages() {
        var container = document.getElementById('chatMessages');
        if (!container) return;
        var html = '';
        state.chatHistory.forEach(function (msg) {
            var cls = msg.role === 'assistant' ? 'db-chat-msg db-chat-msg-assistant' : 'db-chat-msg db-chat-msg-user';
            html += '<div class="' + cls + '">' + escHtml(msg.content) + '</div>';
        });
        container.innerHTML = html;
        container.scrollTop = container.scrollHeight;
    }

    function showTypingIndicator() {
        var container = document.getElementById('chatMessages');
        if (!container) return;
        var el = document.createElement('div');
        el.className = 'db-chat-typing';
        el.id = 'chatTyping';
        el.innerHTML = '<span></span><span></span><span></span>';
        container.appendChild(el);
        container.scrollTop = container.scrollHeight;
    }

    function hideTypingIndicator() {
        var el = document.getElementById('chatTyping');
        if (el) el.remove();
    }

    async function sendChatMessage() {
        var input = document.getElementById('chatInput');
        var message = input.value.trim();
        if (!message) return;
        if (!state.currentEditHtml) return;

        // Push current HTML to undo stack before the edit
        state.htmlUndoStack.push(state.currentEditHtml);
        if (state.htmlUndoStack.length > 20) state.htmlUndoStack.shift();
        updateUndoButton();

        state.chatHistory.push({ role: 'user', content: message });
        renderChatMessages();
        input.value = '';

        var sendBtn = document.getElementById('chatSendBtn');
        if (sendBtn) sendBtn.disabled = true;

        showTypingIndicator();

        // Append uploaded image URL if available
        var messageToSend = message;
        if (state.lastUploadedImageUrl) {
            messageToSend += '\n\n[Hochgeladenes Bild URL: ' + state.lastUploadedImageUrl + ']';
            state.lastUploadedImageUrl = null;
        }

        try {
            var result = await apiPost('/lead/' + state.leadId + '/chat-edit', {
                html: state.currentEditHtml,
                message: messageToSend,
                template_key: state.template,
                history: state.chatHistory.slice(0, -1),
                business_context: {
                    business_name: state.formData.business_name || (state.leadData && state.leadData.business_name) || '',
                    description: state.formData.description || '',
                    category: (state.leadData && state.leadData.category) || '',
                },
            });

            if (result.type === 'edit' && result.html) {
                // AI made an edit — update the preview
                state.currentEditHtml = result.html;
                document.getElementById('editorIframe').srcdoc = result.html;
                state.chatHistory.push({ role: 'assistant', content: result.message || '\u00c4nderung umgesetzt!' });
            } else {
                // Chat-only response — no HTML change, pop undo stack
                state.htmlUndoStack.pop();
                updateUndoButton();
                state.chatHistory.push({ role: 'assistant', content: result.message || 'Ich kann dir dabei leider nicht helfen.' });
            }
        } catch (e) {
            // Error — pop undo stack since no change was made
            state.htmlUndoStack.pop();
            updateUndoButton();
            state.chatHistory.push({ role: 'assistant', content: 'Entschuldigung, da ist etwas schiefgegangen. Versuch es nochmal.' });
            console.error('Chat edit error:', e);
        }

        hideTypingIndicator();
        renderChatMessages();
        if (sendBtn) sendBtn.disabled = false;
    }

    function undoLastEdit() {
        if (!state.htmlUndoStack.length) return;
        state.currentEditHtml = state.htmlUndoStack.pop();
        document.getElementById('editorIframe').srcdoc = state.currentEditHtml;
        updateUndoButton();
        state.chatHistory.push({ role: 'assistant', content: 'Letzte \u00c4nderung r\u00fcckg\u00e4ngig gemacht.' });
        renderChatMessages();
    }

    function updateUndoButton() {
        var btn = document.getElementById('chatUndoBtn');
        if (btn) btn.disabled = !state.htmlUndoStack.length;
    }

    function triggerChatImageUpload() {
        var input = document.getElementById('chatImageInput');
        if (input) input.click();
    }

    async function handleChatImageUpload(input) {
        if (!input.files || !input.files[0]) return;
        var file = input.files[0];

        if (!file.type.startsWith('image/')) {
            alert('Bitte nur Bilddateien hochladen.');
            return;
        }
        if (file.size > 5 * 1024 * 1024) {
            alert('Das Bild ist zu gross (max. 5MB).');
            return;
        }

        state.chatHistory.push({ role: 'user', content: '\ud83d\udcf7 Bild wird hochgeladen: ' + file.name });
        renderChatMessages();
        showTypingIndicator();

        try {
            var formData = new FormData();
            formData.append('image', file);

            var res = await fetch('/api/lead/' + state.leadId + '/upload-chat-image', {
                method: 'POST',
                body: formData,
            });
            var data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Upload fehlgeschlagen');

            state.lastUploadedImageUrl = data.url;

            hideTypingIndicator();
            state.chatHistory[state.chatHistory.length - 1].content = '\ud83d\udcf7 Bild hochgeladen: ' + file.name;
            state.chatHistory.push({
                role: 'assistant',
                content: 'Bild erhalten! Sag mir, wo ich es einsetzen soll (z.B. "Verwende dieses Bild als Hauptbild" oder "Ersetze das Bild im \u00dcber-uns-Bereich").',
            });
            renderChatMessages();
        } catch (e) {
            hideTypingIndicator();
            state.chatHistory[state.chatHistory.length - 1].content = '\ud83d\udcf7 Upload fehlgeschlagen: ' + file.name;
            state.chatHistory.push({ role: 'assistant', content: 'Das Bild konnte leider nicht hochgeladen werden. Versuch es nochmal.' });
            renderChatMessages();
            console.error('Image upload error:', e);
        }

        input.value = '';
    }

    function toggleChat() {
        state.chatPanelOpen = !state.chatPanelOpen;
        var chat = document.getElementById('editorChat');
        var toggle = document.getElementById('chatToggle');
        if (chat) chat.classList.toggle('open', state.chatPanelOpen);
        if (toggle) toggle.classList.toggle('active', state.chatPanelOpen);
    }

    function setDevice(mode) {
        var wrap = document.getElementById('editorIframeWrap');
        if (!wrap) return;
        wrap.classList.toggle('mobile-preview', mode === 'mobile');
        document.querySelectorAll('.db-device-btn').forEach(function (btn) {
            btn.classList.toggle('active', btn.dataset.device === mode);
        });
    }

    async function saveCurrentHtml() {
        if (!state.currentEditHtml || !state.template || !state.leadId) return;
        try {
            await apiPost('/lead/' + state.leadId + '/save-html', {
                html: state.currentEditHtml,
                template_key: state.template,
            });
        } catch (e) {
            console.warn('HTML save failed:', e);
        }
    }

    async function onStep4Next() {
        await saveCurrentHtml();

        if (!state.domainSuggestions.length) {
            generatingOverlay.classList.add('visible');
            await generateDomainSuggestions();
            generatingOverlay.classList.remove('visible');
        }

        renderDomainCards();
        goToStep(5);
    }

    /* ---------- Step 5: Domain suggestions ---------- */
    function toAsciiDomain(name) {
        return name.toLowerCase()
            .replace(/\u00e4/g, 'ae').replace(/\u00f6/g, 'oe').replace(/\u00fc/g, 'ue')
            .replace(/\u00e9|\u00e8|\u00ea/g, 'e')
            .replace(/[\s_]+/g, '-')
            .replace(/[^a-z0-9-]/g, '')
            .replace(/-{2,}/g, '-')
            .replace(/^-|-$/g, '')
            .substring(0, 30);
    }

    async function generateDomainSuggestions() {
        var name = state.formData.business_name || (state.leadData && state.leadData.business_name) || 'meinbusiness';
        var clean = toAsciiDomain(name);
        if (!clean) clean = 'meinbusiness';

        // Full pool of candidates — checked in batches until 3 available found
        var allCandidates = [
            clean + '.ch',
            clean + '.com',
            clean + '-online.ch',
            clean + '-web.ch',
            clean + '-schweiz.ch',
            'mein-' + clean + '.ch',
            clean + '-gmbh.ch',
            clean + '-service.ch',
            clean + '-profi.ch',
            clean + '-ag.ch',
            'team-' + clean + '.ch',
            clean + '-direkt.ch',
        ];

        var available = [];
        var checked = 0;
        var batchSize = 6;

        while (available.length < 3 && checked < allCandidates.length) {
            var batch = allCandidates.slice(checked, checked + batchSize);
            checked += batchSize;
            try {
                var resp = await fetch('/api/check-domains', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ domains: batch }),
                });
                if (resp.ok) {
                    var data = await resp.json();
                    var batchAvail = data.results.filter(function (d) { return d.available === true; });
                    available = available.concat(batchAvail);
                }
            } catch (e) {
                console.warn('Domain check failed:', e);
                break;
            }
        }

        if (available.length > 0) {
            state.domainSuggestions = available.slice(0, 3);
            return;
        }

        // Fallback: show first 3 candidates as unchecked
        state.domainSuggestions = allCandidates.slice(0, 3).map(function (d) {
            var tld = '.' + d.split('.').pop();
            return { domain: d, tld: tld, available: null };
        });
    }

    function renderDomainCards() {
        var list = document.getElementById('domainList');
        var html = '';

        state.domainSuggestions.forEach(function (d, i) {
            var availClass = d.available === true ? ' available' : '';
            var availText = d.available === true ? 'Verf\u00fcgbar' : (d.available === false ? 'Nicht verf\u00fcgbar' : 'Wird gepr\u00fcft\u2026');
            html += '<div class="db-domain-card" data-domain-idx="' + i + '" tabindex="0">';
            html += '<div class="db-radio"><div class="db-radio-dot"></div></div>';
            html += '<div class="db-domain-info">';
            html += '<div class="db-domain-name">' + d.domain + '</div>';
            html += '<div class="db-domain-meta">';
            html += '<span class="db-tld-badge">' + d.tld + '</span>';
            html += '<span class="db-avail"><span class="db-avail-dot' + availClass + '"></span>' + availText + '</span>';
            html += '</div></div>';
            html += '</div>';
        });

        list.innerHTML = html;

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
        document.getElementById('step5NextBtn').disabled = false;
    }

    function onStep5Next() {
        renderReview();
        goToStep(6);
    }

    /* ---------- Step 6: Review ---------- */
    function renderReview() {
        document.getElementById('reviewDomain').textContent = state.domain || '\u2014';
    }

    async function openPreview() {
        var overlay = document.getElementById('previewOverlay');
        var iframe = document.getElementById('previewOverlayIframe');
        var loading = document.getElementById('previewLoading');

        loading.classList.remove('hidden');
        overlay.classList.add('visible');

        if (state.currentEditHtml) {
            iframe.onload = function () { loading.classList.add('hidden'); };
            iframe.srcdoc = state.currentEditHtml;
        } else if (state.generatedUrls[state.template]) {
            iframe.onload = function () { loading.classList.add('hidden'); };
            iframe.src = state.generatedUrls[state.template];
        } else {
            var url = '/api/preview/' + encodeURIComponent(state.leadId) + '/' + state.template;
            iframe.onload = function () { loading.classList.add('hidden'); };
            iframe.src = url;
        }
    }

    function closePreview() {
        var overlay = document.getElementById('previewOverlay');
        var iframe = document.getElementById('previewOverlayIframe');
        var loading = document.getElementById('previewLoading');
        overlay.classList.remove('visible');
        iframe.src = 'about:blank';
        iframe.removeAttribute('srcdoc');
        loading.classList.remove('hidden');
    }

    /* ---------- Order ---------- */
    async function handleOrder() {
        if (!state.agreedToTerms) return;

        var orderBtn = document.getElementById('orderBtn');
        orderBtn.disabled = true;

        steps[6].classList.remove('active');
        document.querySelector('.db-header').style.display = 'none';
        document.querySelector('.db-main').style.display = 'none';
        var paymentEl = document.getElementById('payment');
        paymentEl.style.display = '';
        paymentEl.classList.add('active');
        window.scrollTo(0, 0);

        var sc = document.getElementById('stripe-container');
        if (sc && !sc.querySelector('stripe-pricing-table')) {
            var pt = document.createElement('stripe-pricing-table');
            pt.setAttribute('pricing-table-id', 'prctbl_1TD5B6Co7odLqWDi7TBPULXA');
            pt.setAttribute('publishable-key', 'pk_live_51TCbOwCo7odLqWDi0dVxF2JY6ZckAroieNNOFaZTZ9VMzvlba6ksmQJvt6khUr9eSvW9S2L212dy8FghdgIHisJD00KYBWc53J');
            sc.appendChild(pt);
        }

        var formData = new FormData();
        formData.append('chosen_template', state.template || '');
        formData.append('description', state.customizations.description || '');
        formData.append('values', state.customizations.values || '');
        formData.append('selected_domain', state.domain || '');
        formData.append('agreed_to_terms', 'true');
        if (state.customizations.phone) formData.append('phone', state.customizations.phone);
        if (state.customizations.address) formData.append('address', state.customizations.address);
        if (state.logoFile) formData.append('logo', state.logoFile);
        state.imageFiles.forEach(function (f) { formData.append('images', f); });

        apiPostOrder(state.leadId, formData).then(function (result) {
            if (result && result.live_url) window._liveUrl = result.live_url;
        }).catch(function (err) {
            console.error('Order background error:', err);
        });
    }

    /* ---------- Step navigation via progress dots ---------- */
    function navStep(n) {
        if (n > highestStepReached || n === state.currentStep) return;

        if (state.currentStep === 4 && state.currentEditHtml) saveCurrentHtml();

        if (n === 2) renderInfoForm();
        if (n === 3) { initTemplateStep(); setTimeout(scaleIframes, 50); }
        if (n === 4 && state.template) initChatEditor();
        if (n === 5 && state.domainSuggestions.length) renderDomainCards();
        if (n === 6) renderReview();
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
    window.dbGoBack = function (n) {
        if (state.currentStep === 4 && state.currentEditHtml) saveCurrentHtml();
        goToStep(n);
    };
    window.dbStep2Next = onStep2Next;
    window.dbStep3Next = onStep3Next;
    window.dbStep4Next = onStep4Next;
    window.dbStep5Next = onStep5Next;
    window.dbGoHome = function () { window.location.href = 'index.html'; };
    window.dbNavStep = function (n) { navStep(n); };
    window.dbOpenPreview = openPreview;
    window.dbClosePreview = closePreview;
    window.dbChatSend = sendChatMessage;
    window.dbToggleChat = toggleChat;
    window.dbSetDevice = setDevice;
    window.dbUndo = undoLastEdit;
    window.dbChatUpload = triggerChatImageUpload;
    window.__chatImageChanged = handleChatImageUpload;

    /* ---------- Start ---------- */
    document.addEventListener('DOMContentLoaded', function () {
        init();
        scaleIframes();
        window.addEventListener('resize', scaleIframes);
        setTimeout(scaleIframes, 500);
    });
})();
