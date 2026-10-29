# Third-party attribution — review inventory

Updated by Phase 5D-R1: original team-owned work is covered by the operative root [MIT LICENSE](../../LICENSE), **Copyright (c) 2026 Ghost Protocol Contributors**, following the project owner's explicit authorization for Members A, B and C. Third-party material remains under its own terms; the project MIT grant does not relicense it. This inventory is not legal clearance for unknown external material. The machine-readable [dependency inventory](dependency-licenses.json) records 466 npm lock entries and 89 installed Python distribution records across the two separate environments. Duplicate Python distributions are intentional. Package versions come from reviewed locks.

## Material actually included

| Material | Declared license / handling |
| --- | --- |
| Next.js, React, React DOM, Tailwind CSS | MIT. Preserve the [Next](licenses/next-MIT.txt), [React](licenses/react-MIT.txt), [React DOM](licenses/react-dom-MIT.txt) and [Tailwind](licenses/tailwind-MIT.txt) notices copied verbatim from the installed packages. |
| Lucide React icons | ISC; [preserved notice](licenses/lucide-ISC.txt). Icons used by the interface retain that license. |
| Inter Variable and Space Grotesk Variable | SIL Open Font License 1.1; [Inter notice](licenses/inter-OFL-1.1.txt), [Space Grotesk notice](licenses/space-grotesk-OFL-1.1.txt). Fonts are installed through pinned Fontsource packages. Do not remove copyright/reserved-name conditions or claim ownership. |
| Existing frontend screenshots | Four selected synthetic local-backend captures, copied unchanged into `docs/assets/frontend/`. They include rendered third-party typefaces/icons; they do not grant ownership of those assets or sponsor marks. |
| Original Member A/B/C source and team assets | The owner explicitly confirmed team agreement to MIT for original contributions and redistribution of original team visual assets. This does not extend to any independently licensed third-party code. |
| Synthetic fixtures | Team-owned original fixtures remain synthetic, unchanged and within the approved original-contribution scope. No real documents or email are supplied. |

The npm inventory also contains Apache-2.0, ISC, BSD, BlueOak-1.0.0, Python-2.0, CC0, CC-BY-4.0, MPL-2.0 and LGPL-3.0-or-later expressions, including combined licenses. In particular, optional Sharp/libvips binaries have LGPL-related obligations. **`node_modules`, native binaries and build artifacts are excluded from the source publication manifest.** Installing a dependency does not relicense it. Any later redistribution of native binaries, generated bundles, containers or a public static demo requires a review of that exact artifact and its required notices/source obligations.

Python metadata includes permissive licenses and MPL-2.0 (`certifi`). Where metadata says UNKNOWN or supplies full license text instead of an SPDX identifier, classifiers and installed license files must be consulted; do not convert UNKNOWN into an invented permission. For the current inventory, aiosqlite identifies MIT via classifier/license text, and colorama identifies BSD via classifier/license text. The inventory preserves the original metadata rather than assigning an unverified SPDX grant. Hashes of the seven copied notice files are recorded in the inventory.

## Approved original-project license

The approved operative license is **MIT for original team-owned project contributions**, with the exact collective notice supplied by the owner. Root `LICENSE` and `public-demo/LICENSE` contain the complete standard MIT text. The earlier [draft](license-proposals/MIT-LICENSE.DRAFT.txt) is retained as historical review evidence and has no operative effect. Third-party material remains under its existing terms and original notices. No individual author identity is inferred for a future Git commit.

The earlier Apache-2.0 alternative was not selected. The official [MIT text](https://opensource.org/license/mit) and [OFL text](https://openfontlicense.org/open-font-license-official-text/) remain useful references; separate font licensing is preserved.

## Provider, model and trademark boundaries

No NVIDIA model weights, OpenShell executable, Nebius service entitlement, sponsor logo pack or third-party private credential is bundled in the publication candidate. Nebius Token Factory access and any NVIDIA Nemotron model usage remain subject to their own service/model terms; no redistribution permission is inferred from a Python client dependency. Sponsor/product names describe the hackathon and implementation, not endorsement or a trademark license.

## Required release review

1. Original team contribution/asset authorization is recorded in [the Phase 5D-R1 report](PHASE5D_R1_FINAL_RELEASE_APPROVAL.md); do not request it again for the same approved scope.
2. Preserve the operative MIT files and exact collective attribution. Review additional third-party material separately if introduced later.
3. Retain this inventory and copied notices. Review the exact distributable again if shipping installed packages/binaries/build output rather than source.
4. Recheck dependency license/advisory metadata when locks change. This inventory is time-specific and is not a certified SBOM.
