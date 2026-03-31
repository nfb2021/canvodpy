// MathJax configuration for pymdownx.arithmatex (generic = true).
// arithmatex wraps display math in <div class="arithmatex">\[...\]</div>
// and inline math in <span class="arithmatex">\(...\)</span>.
// MathJax must be configured BEFORE the main MathJax bundle loads.

window.MathJax = {
  tex: {
    inlineMath: [["\\(", "\\)"]],
    displayMath: [["\\[", "\\]"]],
    processEscapes: true,
    processEnvironments: true,
  },
  options: {
    ignoreHtmlClass: ".*|",
    processHtmlClass: "arithmatex",
  },
};

// Re-render math after every instant-navigation page swap.
// Required because navigation.instant replaces DOM content via XHR
// without reloading scripts, so MathJax's initial typeset is wiped.
document$.subscribe(() => {
  MathJax.startup.output.clearCache();
  MathJax.typesetClear();
  MathJax.texReset();
  MathJax.typesetPromise();
});
