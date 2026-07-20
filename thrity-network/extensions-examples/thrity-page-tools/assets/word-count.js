// Runs as ordinary page JavaScript - injected on demand via
// run_page_script() from extension.thrity.
(function () {
    var text = document.body ? document.body.innerText : "";
    var words = text.trim().split(/\s+/).filter(Boolean);
    alert("This page has about " + words.length + " words.");
})();
