/* ============================================
   WebsiteBuilder — App JS
   Stryds-replica interactions
   ============================================ */

(function () {

    /* --------------------------------------------------
       1. HERO SLIDE SWITCHING
       Switches between brand-intro and problem-statement
       based on scroll progress through .hero-wrapper
    -------------------------------------------------- */
    const heroWrapper = document.querySelector('.hero-wrapper');
    const slide1 = document.getElementById('slide-1');
    const slide2 = document.getElementById('slide-2');

    function updateHeroSlides() {
        if (!heroWrapper || !slide1 || !slide2) return;

        const rect   = heroWrapper.getBoundingClientRect();
        const scrolled = Math.max(0, -rect.top);          // px scrolled into hero
        const range    = rect.height - window.innerHeight; // total scrollable range
        const progress = Math.min(1, scrolled / range);   // 0 → 1

        // Slide 1: visible during first 40% of hero scroll
        // Slide 2: visible after 40%
        if (progress < 0.42) {
            slide1.classList.add('active');
            slide2.classList.remove('active');
        } else {
            slide2.classList.add('active');
            slide1.classList.remove('active');
        }
    }

    /* --------------------------------------------------
       2. SCROLL FADE-IN (data-fade elements)
    -------------------------------------------------- */
    const fadeObserver = new IntersectionObserver(
        (entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('visible');
                }
            });
        },
        { threshold: 0.18 }
    );
    document.querySelectorAll('[data-fade]').forEach(el => fadeObserver.observe(el));

    /* --------------------------------------------------
       3. FEATURE CARD SCALE EFFECT
       Subtle scale-down on cards that are "behind"
       the active sticky card
    -------------------------------------------------- */
    const featureCards = document.querySelectorAll('.feature-card');

    function updateFeatureCards() {
        featureCards.forEach((card, i) => {
            const rect = card.getBoundingClientRect();
            const isStuck = rect.top <= (2 + i * 2) * 16 + 2; // approx top rem value
            if (isStuck && i < featureCards.length - 1) {
                card.style.transform = 'scale(0.98)';
                card.style.opacity   = '0.85';
            } else {
                card.style.transform = '';
                card.style.opacity   = '';
            }
        });
    }

    /* --------------------------------------------------
       4. UNIFIED SCROLL HANDLER
    -------------------------------------------------- */
    function onScroll() {
        updateHeroSlides();
        updateFeatureCards();
    }

    window.addEventListener('scroll', onScroll, { passive: true });

    // Run on load
    updateHeroSlides();
    updateFeatureCards();

    /* --------------------------------------------------
       5. SMOOTH ANCHOR SCROLL
    -------------------------------------------------- */
    document.querySelectorAll('a[href^="#"]').forEach(link => {
        link.addEventListener('click', e => {
            const target = document.querySelector(link.getAttribute('href'));
            if (target) {
                e.preventDefault();
                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    });

})();
