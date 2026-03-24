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
        earlydog: { label: 'Verspielt & modern', tags: ['Handwerker', 'Coiffeure', 'Reinigungen'] },
        bia: { label: 'Premium & editorial', tags: ['Agenturen', 'Architekten', 'Berater', 'Anw\u00e4lte'] },
        liveblocks: { label: 'Modern & technisch', tags: ['IT-Firmen', 'Startups', 'Tech'] },
        loveseen: { label: 'Luxuri\u00f6s & editorial', tags: ['Beauty', 'Wellness', 'Fotografen'] },
    };

    /* ---------- Fallback preview URLs (API now always returns real preview URLs) ---------- */
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
        leadData: null,         // API response from /api/lead/<id>
        isNoCode: false,        // true if user entered via email (no code)
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
        tempLogoUrl: '',        // Cached data URL for logo
        tempImageUrls: [],      // Cached data URLs for images
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
        for (let i = 1; i <= 5; i++) {
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
                updateTemplateIframes();
                goToStep(2);
            }
        });

        // Step 1: Email — async submit (no-code flow)
        document.getElementById('emailForm').addEventListener('submit', async function (e) {
            e.preventDefault();
            if (await validateAndRegisterEmail()) {
                state.isNoCode = true;
                // For no-code users: show placeholder previews
                updateTemplateIframesFallback();
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

        // Basic email validation
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val)) {
            showInputError(input, error, 'Bitte gib eine g\u00fcltige E-Mail-Adresse ein.');
            return false;
        }

        // Show loading state
        var originalText = btn.innerHTML;
        btn.disabled = true;
        btn.textContent = 'Laden\u2026';

        try {
            var data = await apiPost('/lead/register', { email: val });
            state.leadId = data.lead_id;
            state.leadData = data;
            // No domain suggestions yet for no-code users — generated after Step 3
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
        // Re-trigger shake
        input.style.animation = 'none';
        input.offsetHeight;
        input.style.animation = '';
    }

    /* ---------- Step 2: Template selection ---------- */
    function updateTemplateIframes(onlySelected) {
        if (!state.leadData || !state.leadData.previews) return;
        var cards = document.querySelectorAll('.db-tpl-card');
        var hasImages = state.logoFile || state.imageFiles.length;

        cards.forEach(function (card, i) {
            // On initial load (no template selected yet), update ALL cards
            // After selection, only update the selected template (saves 3x AI calls + image uploads)
            if (state.template && card.dataset.tpl !== state.template) return;

            var iframe = card.querySelector('.db-preview-iframe');
            if (!iframe) return;

            if (hasImages) {
                // POST images to server for AI-powered placement
                fetchPreviewWithImages(card.dataset.tpl, iframe);
            } else {
                var url = state.leadData.previews[i];
                if (!url) return;
                var params = new URLSearchParams();
                if (state.customizations.description) params.set('description', state.customizations.description);
                if (state.customizations.values) params.set('values', state.customizations.values);
                if (state.customizations.phone) params.set('phone', state.customizations.phone);
                if (state.customizations.address) params.set('address', state.customizations.address);
                var sep = url.includes('?') ? '&' : '?';
                iframe.src = params.toString() ? url + sep + params.toString() : url;
            }
        });
    }

    // For no-code users: show plain template placeholders
    function updateTemplateIframesFallback() {
        var cards = document.querySelectorAll('.db-tpl-card');
        cards.forEach(function (card) {
            var iframe = card.querySelector('.db-preview-iframe');
            if (!iframe) return;
            var tpl = card.dataset.tpl;
            iframe.src = fallbackPreviewUrls[tpl] || ('/api/preview/_fallback/' + tpl);
        });
    }

    function fetchPreviewWithImages(templateKey, iframe) {
        var formData = new FormData();
        formData.append('lead_id', state.leadId);
        formData.append('template', templateKey);
        formData.append('description', state.customizations.description || '');
        formData.append('values', state.customizations.values || '');
        if (state.customizations.phone) formData.append('phone', state.customizations.phone);
        if (state.customizations.address) formData.append('address', state.customizations.address);
        if (state.logoFile) formData.append('logo', state.logoFile);
        state.imageFiles.forEach(function (f) { formData.append('images', f); });

        fetch('/api/preview-with-images', { method: 'POST', body: formData })
            .then(function (resp) {
                if (!resp.ok) throw new Error('Preview failed: ' + resp.status);
                return resp.text();
            })
            .then(function (html) {
                iframe.srcdoc = html;
            })
            .catch(function (e) {
                console.warn('Preview with images failed:', e);
                var url = '/api/preview/' + encodeURIComponent(state.leadId) + '/' + templateKey;
                iframe.src = url;
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

        badge.textContent = cfg.label;

        var html = '';
        var isRequired = state.isNoCode;
        var reqLabel = isRequired ? ' <span style="color:var(--red);">*</span>' : '';
        var reqAttr = isRequired ? ' required' : '';

        // Business name (only for no-code users who don't have one yet)
        if (state.isNoCode) {
            html += '<div class="db-input-group">';
            html += '<label class="db-label" for="f_business_name">FIRMENNAME <span style="color:var(--red);">*</span></label>';
            html += '<p class="db-field-hint">Der Name deines Unternehmens, wie er auf der Website erscheinen soll.</p>';
            html += '<input class="db-input" type="text" id="f_business_name" name="business_name" placeholder="z.B. Maler Meier AG" required>';
            html += '</div>';
        }

        // Description — the AI figures out the rest
        html += '<div class="db-input-group">';
        html += '<label class="db-label" for="f_description">BESCHREIBE DEIN BUSINESS' + reqLabel + '</label>';
        html += '<p class="db-field-hint">Was macht dein Unternehmen? Die KI erstellt daraus alle Texte f\u00fcr deine Website.</p>';
        html += '<textarea class="db-input db-textarea" id="f_description" name="description" rows="5" placeholder="z.B. Wir sind ein Malergesch\u00e4ft in Z\u00fcrich, spezialisiert auf Fassaden und Innenr\u00e4ume. Seit 20 Jahren bieten wir hochwertige Arbeit f\u00fcr Privatkunden und Unternehmen. Unser Team besteht aus 8 erfahrenen Malern."' + reqAttr + '></textarea>';
        html += '</div>';

        // Values
        html += '<div class="db-input-group">';
        html += '<label class="db-label" for="f_values">WERTE & BESONDERHEITEN' + reqLabel + '</label>';
        html += '<p class="db-field-hint">Was macht dich besonders? Die KI nutzt das f\u00fcr Slogans, Statistiken und Highlights.</p>';
        html += '<textarea class="db-input db-textarea" id="f_values" name="values" rows="3" placeholder="z.B. 20 Jahre Erfahrung, 500+ zufriedene Kunden, Familienunternehmen, kostenlose Beratung"' + reqAttr + '></textarea>';
        html += '</div>';

        // Contact info (only for no-code users)
        if (state.isNoCode) {
            html += '<div class="db-input-group">';
            html += '<label class="db-label" for="f_phone">TELEFONNUMMER</label>';
            html += '<p class="db-field-hint">Wird auf deiner Website angezeigt, damit Kunden dich erreichen k\u00f6nnen.</p>';
            html += '<input class="db-input" type="tel" id="f_phone" name="phone" placeholder="z.B. +41 44 123 45 67">';
            html += '</div>';

            html += '<div class="db-input-group">';
            html += '<label class="db-label" for="f_address">ADRESSE</label>';
            html += '<p class="db-field-hint">Firmenadresse f\u00fcr den Kontaktbereich deiner Website.</p>';
            html += '<input class="db-input" type="text" id="f_address" name="address" placeholder="z.B. Bahnhofstrasse 10, 8001 Z\u00fcrich">';
            html += '</div>';
        }

        // Logo upload
        html += '<div class="db-input-group">';
        html += '<label class="db-label">LOGO</label>';
        html += '<label class="db-file-upload" id="fileLabel_logo">';
        html += '<input type="file" accept="image/*" style="display:none" onchange="window.__fileChanged(this,\'logo\')">';
        html += 'Datei ausw\u00e4hlen\u2026';
        html += '</label>';
        html += '</div>';

        // General images — show existing + add more
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

        // Render existing images if returning to step 3
        setTimeout(function () { renderImageList(); }, 0);

        // Show existing logo name if set
        if (state.logoFile) {
            var logoLabel = document.getElementById('fileLabel_logo');
            if (logoLabel) {
                logoLabel.classList.add('has-file');
                logoLabel.childNodes[logoLabel.childNodes.length - 1].textContent = ' ' + state.logoFile.name;
            }
        }
    }

    // File upload label update + store file references in state
    window.__fileChanged = function (input, key) {
        var label = document.getElementById('fileLabel_' + key);
        if (input.files.length) {
            if (key === 'logo') {
                state.logoFile = input.files[0];
                state.tempLogoUrl = '';
                label.classList.add('has-file');
                label.childNodes[label.childNodes.length - 1].textContent = ' ' + input.files[0].name;
            } else if (key === 'images') {
                // Accumulate images (don't replace)
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
        if (!state.imageFiles.length) {
            container.innerHTML = '';
            return;
        }
        var html = '';
        state.imageFiles.forEach(function (f, i) {
            html += '<div class="db-image-item">';
            html += '<span class="db-image-name">' + f.name + '</span>';
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
        var c = state.customizations;
        c.description = getVal('description');
        c.values = getVal('values');
        // Collect business name + contact info for no-code users
        if (state.isNoCode) {
            var bizName = getVal('business_name');
            if (bizName && state.leadData) {
                state.leadData.business_name = bizName;
            }
            c.phone = getVal('phone');
            c.address = getVal('address');
        }
    }

    function getVal(name) {
        var el = document.getElementById('f_' + name);
        return el ? el.value.trim() : '';
    }

    function hasAnyCustomization() {
        var c = state.customizations;
        return !!(c.description || c.values);
    }

    async function onStep3Next() {
        collectFormData();

        // For no-code users: description and values are required
        if (state.isNoCode) {
            var descEl = document.getElementById('f_description');
            var valEl = document.getElementById('f_values');
            var bizEl = document.getElementById('f_business_name');

            if (bizEl && !bizEl.value.trim()) {
                bizEl.focus();
                bizEl.classList.add('error');
                return;
            }
            if (!state.customizations.description) {
                descEl.focus();
                descEl.classList.add('error');
                return;
            }
            if (!state.customizations.values) {
                valEl.focus();
                valEl.classList.add('error');
                return;
            }
        }

        // Show generating overlay
        generatingOverlay.classList.add('visible');

        // Generate domain suggestions (async — checks real availability)
        if (!state.domainSuggestions.length) {
            await generateDomainSuggestions();
        }

        if (hasAnyCustomization() || state.logoFile || state.imageFiles.length) {
            // For no-code users: update lead data on server with business info before generating
            if (state.isNoCode && state.leadData.business_name) {
                try {
                    var updateData = {
                        business_name: state.leadData.business_name,
                        description: state.customizations.description,
                        values: state.customizations.values,
                        phone: state.customizations.phone || '',
                        address: state.customizations.address || '',
                        chosen_template: state.template || '',
                    };
                    // Include domain suggestions if already generated
                    if (state.domainSuggestions.length) {
                        state.domainSuggestions.forEach(function (d, i) {
                            if (i < 3) updateData['domain_option_' + (i + 1)] = d.domain;
                        });
                    }
                    await apiPost('/lead/' + state.leadId + '/update', updateData);
                } catch (e) { console.warn('Lead update failed:', e); }
            }

            // Start updating only the selected template iframe
            updateTemplateIframes();

            // Wait for the selected template iframe to load, then proceed
            var done = false;
            var selectedCard = document.querySelector('.db-tpl-card[data-tpl="' + state.template + '"]');
            var selectedIframe = selectedCard ? selectedCard.querySelector('.db-preview-iframe') : null;

            var proceed = function () {
                if (done) return;
                done = true;
                generatingOverlay.classList.remove('visible');
                renderDomainCards();
                goToStep(4);
            };

            if (selectedIframe) {
                selectedIframe.addEventListener('load', proceed, { once: true });
            }

            // Timeout fallback: proceed after 90s max
            setTimeout(proceed, 90000);
        } else {
            generatingOverlay.classList.remove('visible');
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
        var name = (state.leadData && state.leadData.business_name) || 'meinbusiness';
        var clean = toAsciiDomain(name);
        if (!clean) clean = 'meinbusiness';

        // Generate more candidates to find available ones
        var candidates = [
            clean + '.ch',
            clean + '.com',
            clean + '-online.ch',
            clean + '-web.ch',
            clean + '-schweiz.ch',
            'mein-' + clean + '.ch',
        ];

        // Check availability via API
        try {
            var resp = await fetch('/api/check-domains', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ domains: candidates }),
            });
            if (resp.ok) {
                var data = await resp.json();
                // Only show available domains (max 3)
                var available = data.results.filter(function (d) { return d.available === true; });
                if (available.length > 0) {
                    state.domainSuggestions = available.slice(0, 3);
                    return;
                }
            }
        } catch (e) {
            console.warn('Domain check failed:', e);
        }

        // Fallback if API fails: show candidates but mark as unchecked
        state.domainSuggestions = candidates.slice(0, 3).map(function (d) {
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
        var overlay = document.getElementById('previewOverlay');
        var iframe = document.getElementById('previewOverlayIframe');
        var loading = document.getElementById('previewLoading');

        loading.classList.remove('hidden');
        overlay.classList.add('visible');

        var hasImages = state.logoFile || state.imageFiles.length;

        if (hasImages) {
            // POST images to server for AI placement
            try {
                var formData = new FormData();
                formData.append('lead_id', state.leadId);
                formData.append('template', state.template);
                formData.append('description', state.customizations.description || '');
                formData.append('values', state.customizations.values || '');
                if (state.logoFile) formData.append('logo', state.logoFile);
                state.imageFiles.forEach(function (f) { formData.append('images', f); });

                var resp = await fetch('/api/preview-with-images', { method: 'POST', body: formData });
                if (!resp.ok) throw new Error('Status ' + resp.status);
                var html = await resp.text();
                iframe.onload = function () { loading.classList.add('hidden'); };
                iframe.srcdoc = html;
            } catch (e) {
                console.warn('Preview with images failed:', e);
                iframe.onload = function () { loading.classList.add('hidden'); };
                iframe.src = '/api/preview/' + encodeURIComponent(state.leadId) + '/' + state.template;
            }
        } else {
            var url = '';
            if (state.leadData && state.leadData.previews) {
                var idx = TEMPLATE_KEYS.indexOf(state.template);
                if (idx >= 0) url = state.leadData.previews[idx];
            }
            if (!url) url = '/api/preview/' + encodeURIComponent(state.leadId) + '/' + state.template;
            var params = new URLSearchParams();
            if (state.customizations.description) params.set('description', state.customizations.description);
            if (state.customizations.values) params.set('values', state.customizations.values);
            var sep = url.includes('?') ? '&' : '?';
            var fullUrl = params.toString() ? url + sep + params.toString() : url;
            iframe.onload = function () { loading.classList.add('hidden'); };
            iframe.src = fullUrl;
        }
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
        orderBtn.disabled = true;

        // Show Stripe payment screen IMMEDIATELY (don't wait for build/deploy)
        steps[5].classList.remove('active');
        document.querySelector('.db-header').style.display = 'none';
        document.querySelector('.db-main').style.display = 'none';
        var paymentEl = document.getElementById('payment');
        paymentEl.style.display = '';
        paymentEl.classList.add('active');
        window.scrollTo(0, 0);

        // Inject Stripe pricing table (script already preloaded in <head>)
        var sc = document.getElementById('stripe-container');
        if (sc && !sc.querySelector('stripe-pricing-table')) {
            var pt = document.createElement('stripe-pricing-table');
            pt.setAttribute('pricing-table-id', 'prctbl_1TD5B6Co7odLqWDi7TBPULXA');
            pt.setAttribute('publishable-key', 'pk_live_51TCbOwCo7odLqWDi0dVxF2JY6ZckAroieNNOFaZTZ9VMzvlba6ksmQJvt6khUr9eSvW9S2L212dy8FghdgIHisJD00KYBWc53J');
            sc.appendChild(pt);
        }

        // Fire build/deploy in the background — don't block the payment screen
        var formData = new FormData();
        formData.append('chosen_template', state.template || '');
        formData.append('description', state.customizations.description || '');
        formData.append('values', state.customizations.values || '');
        formData.append('selected_domain', state.domain || '');
        formData.append('agreed_to_terms', 'true');
        if (state.customizations.phone) formData.append('phone', state.customizations.phone);
        if (state.customizations.address) formData.append('address', state.customizations.address);
        if (state.logoFile) {
            formData.append('logo', state.logoFile);
        }
        state.imageFiles.forEach(function (f) {
            formData.append('images', f);
        });

        apiPostOrder(state.leadId, formData).then(function (result) {
            if (result && result.live_url) {
                window._liveUrl = result.live_url;
            }
        }).catch(function (err) {
            console.error('Order background error:', err);
        });
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
