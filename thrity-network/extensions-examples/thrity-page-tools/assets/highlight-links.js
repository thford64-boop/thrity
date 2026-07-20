// Runs as ordinary page JavaScript (same sandbox any website's own
// script runs in) - injected on demand via run_page_script() from
// extension.thrity. Outlines every link that points off the current
// site, so external links are obvious at a glance.
(function () {
    var here = window.location.hostname;
    var links = document.querySelectorAll("a[href]");
    var count = 0;
    links.forEach(function (a) {
        try {
            var url = new URL(a.href, window.location.href);
            if (url.hostname && url.hostname !== here) {
                a.style.outline = "2px solid #4dd0e1";
                a.style.outlineOffset = "2px";
                count++;
            }
        } catch (e) {
            // ignore malformed hrefs (mailto:, javascript:, etc.)
        }
    });
    console.log("[Thrity Page Tools] highlighted " + count + " external link(s)");
})();
