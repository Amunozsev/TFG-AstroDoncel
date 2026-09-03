export default function About() {
  return (
    <main className="page-shell about-page" id="main-content" tabIndex="-1">
      <header className="page-header">
        <div>
          <p className="eyebrow">Universidad de Alcalá · 2026</p>
          <h1>About AstroDoncel Studio</h1>
          <p className="page-subtitle">Project authorship, scientific provenance and the people and software this portal builds upon.</p>
        </div>
      </header>
      <section className="about-grid" aria-label="AstroDoncel Studio credits">
        <article>
          <h2>Project</h2>
          <p>AstroDoncel Studio is the Bachelor’s Thesis project of <strong>Alfonso Muñoz Sevillano</strong> at the Universidad de Alcalá. It extends the original AstroDoncel portal with a web workflow for discovering, processing and comparing solar radio spectrograms.</p>
        </article>
        <article>
          <h2>e-CALLISTO network</h2>
          <p>FITS observations are provided by the international e-CALLISTO network and its ETHZ/FHNW archive. Credit belongs to Christian Monstein, the participating observatories and the teams that operate and publish the instruments and data.</p>
          <a href="https://www.e-callisto.org/Data/data.html" target="_blank" rel="noreferrer">e-CALLISTO data archive</a>
        </article>
        <article>
          <h2>Original AstroDoncel portal</h2>
          <p>The Universidad de Alcalá AstroDoncel portal is the product and catalogue reference for this project. The NAS deployment reads its current Burst Reports database, while the published monthly catalogues remain available as an explicit fallback. Catalogue events are kept distinct from ML candidates and heuristics.</p>
          <a href="https://astrodoncel.uah.es/dashboard/" target="_blank" rel="noreferrer">Original AstroDoncel portal</a>
        </article>
        <article>
          <h2>Sahan S. Liyanage</h2>
          <p>The e-CALLISTO FITS Analyzer and Burst_No_Burst projects by <strong>Sahan S. Liyanage</strong> are reference implementations for processing, RFI mitigation, comparison, measurement and burst-detection workflows adapted here with project-specific changes and tests.</p>
          <p className="about-links"><a href="https://github.com/SaanDev/e-Callisto_FITS_Analyzer" target="_blank" rel="noreferrer">e-CALLISTO FITS Analyzer</a><a href="https://doi.org/10.1093/rasti/rzag056" target="_blank" rel="noreferrer">Published software article</a></p>
        </article>
        <article>
          <h2>Open-source ecosystem</h2>
          <p>AstroDoncel Studio uses FastAPI, Astropy, SunPy, NumPy, SciPy, SQLAlchemy, ONNX Runtime, React, Vite and Plotly. Their licences and the detailed provenance register are maintained in <code>THIRD_PARTY_NOTICES.md</code>.</p>
        </article>
        <article>
          <h2>Scientific scope</h2>
          <p>The detector supports research triage, not authoritative space-weather alerts. Instrumental measurements, model inferences and visual heuristics are labelled separately and require expert interpretation.</p>
        </article>
      </section>
    </main>
  );
}
