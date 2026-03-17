// Force mermaid to use "base" theme so Material's themeCSS (which uses
// --md-mermaid-* CSS variables from canvod-nordic.css) takes full effect.
// Without this, mermaid's "default" theme generates hardcoded blue inline styles.

// Our script loads AFTER Material's bundle, but Material lazily renders
// mermaid diagrams via IntersectionObserver. Re-initialize before any
// diagram actually renders.
if (typeof mermaid !== "undefined") {
  mermaid.initialize({
    startOnLoad: false,
    theme: "base",
    themeVariables: {
      fontFamily: '"Space Grotesk", system-ui, sans-serif',
    },
  });
}

// Theme toggle: reload to re-render mermaid with correct color scheme.
document.addEventListener("DOMContentLoaded", function () {
  var observer = new MutationObserver(function (mutations) {
    mutations.forEach(function (mutation) {
      if (mutation.attributeName === "data-md-color-scheme") {
        location.reload();
      }
    });
  });

  var body = document.querySelector("body");
  if (body) {
    observer.observe(body, { attributes: true, attributeFilter: ["data-md-color-scheme"] });
  }
});
