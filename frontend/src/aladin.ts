// Aladin Lite v3 (CDS, Université de Strasbourg; GPL-3.0) for the all-sky view.
// We load it at run time from jsDelivr instead of bundling it: our code stays MIT,
// the GPL library stays a separate work, and the page does not grow by 2.4 MB.
// The version is pinned, and the browser checks the file against a SHA-384 hash
// before we run it, so a changed file on the CDN is refused, not executed.
// 3.8.2 is also the version IRSA's own SPHEREx HiPS page uses.

export const ALADIN_VERSION = "3.8.2";
const URL_ = `https://cdn.jsdelivr.net/npm/aladin-lite@${ALADIN_VERSION}/dist/aladin.js`;
const SRI = "sha384-/ymkiSIIZYSHUE2kIcPf4PWW4meM/MIvDZbgCurNjz4k6/Fe21cxLQ9cEn0DlBsZ";

// We type only the few calls we use; Aladin Lite ships no TypeScript types.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AladinNS = any;

let loading: Promise<AladinNS> | null = null;

export function loadAladin(): Promise<AladinNS> {
  if (!loading) {
    loading = (async () => {
      const r = await fetch(URL_, { integrity: SRI, mode: "cors" });
      if (!r.ok) throw new Error(`Could not download Aladin Lite (HTTP ${r.status}).`);
      // The file is one self-contained ES module (its WebAssembly is inlined), so we
      // can run the verified bytes from a blob URL.
      const blobUrl = URL.createObjectURL(new Blob([await r.text()], { type: "text/javascript" }));
      const mod = await import(/* @vite-ignore */ blobUrl);
      const A = mod.default;
      await A.init;
      return A;
    })();
    loading.catch(() => { loading = null; }); // allow a retry after a failure
  }
  return loading;
}
