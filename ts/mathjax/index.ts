// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

/// <reference types="./mathjax-types" />

const packages = ["noerrors", "mathtools"];

function packagesForLoading(packages: string[]): string[] {
    return packages.map((value: string): string => `[tex]/${value}`);
}

window.MathJax = {
    tex: {
        displayMath: [["\\[", "\\]"]],
        processEscapes: false,
        processEnvironments: false,
        processRefs: false,
        packages: {
            "[+]": packages,
            "[-]": ["textmacros"],
        },
    },
    loader: {
        load: packagesForLoading(packages),
        // These extensions are already bundled in tex-chtml-full, so loading them
        // by name emits a harmless "No version information available" console
        // warning. Silence it; it has no effect on rendering.
        versionWarnings: false,
        paths: {
            mathjax: "/_anki/js/vendor/mathjax",
        },
    },
    startup: {
        typeset: false,
    },
};
