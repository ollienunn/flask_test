// ...new file...
document.addEventListener('DOMContentLoaded', function () {
    // ensure page is visible on load (in case class persisted)
    document.body.classList.remove('page-out');

    const NAV_DURATION = 320; // must match CSS transition duration

    function isLocalLink(a) {
        const href = a.getAttribute('href');
        if (!href) return false;
        if (href.startsWith('#')) return false;            // same-page anchor
        if (a.target && a.target !== '' && a.target !== '_self') return false;
        if (a.hasAttribute('download')) return false;
        try {
            const url = new URL(href, location.href);
            return url.origin === location.origin;
        } catch (err) {
            return false;
        }
    }

    // capture clicks on any anchor and handle internal links
    document.addEventListener('click', function (e) {
        const a = e.target.closest('a');
        if (!a) return;
        if (!isLocalLink(a)) return;
        // allow modifier keys (open in new tab/window)
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        // opt-out: data-no-transition attribute
        if (a.dataset.noTransition !== undefined) return;

        e.preventDefault();
        const dest = new URL(a.getAttribute('href'), location.href).href;
        document.body.classList.add('page-out');
        setTimeout(function () { location.href = dest; }, NAV_DURATION);
    }, true);
});