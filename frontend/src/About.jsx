const REPO = 'https://github.com/Amunozsev/TFG-AstroDoncel';

function Link({ href, children }) {
  return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
}

export default function About() {
  return (
    <main className="page-shell about-page" id="main-content" tabIndex="-1">
      <header className="page-header">
        <div>
          <p className="eyebrow">Universidad de Alcalá · 2026</p>
          <h1>About AstroDoncel Studio</h1>
        </div>
      </header>
      <div className="about-body">
        <p className="about-lead">
          AstroDoncel Studio is a web workspace to explore, process and compare solar radio spectrograms from the
          e‑CALLISTO network. It is the Bachelor’s Thesis of <strong>Alfonso Muñoz Sevillano</strong> at the Universidad
          de Alcalá and extends the university’s AstroDoncel portal.
        </p>
        <p className="about-links"><Link href={REPO}>Source code</Link><Link href={`${REPO}/blob/main/MODEL_CARD.md`}>Detector model card</Link></p>

        <section className="about-row">
          <h2>Data</h2>
          <div>
            <p><strong>e‑CALLISTO.</strong> Spectrograms come from the international e‑CALLISTO network, led by Christian
              Monstein, through the FHNW/ETHZ archive. Credit belongs to the observatories that operate the receivers.</p>
            <p><strong>AstroDoncel portal.</strong> Burst Reports, Statistics and Xmatch use the burst catalogue of the
              original AstroDoncel portal of the Universidad de Alcalá.</p>
            <p><strong>GOES.</strong> The X-ray flux overlay uses NOAA GOES XRS data, retrieved with SunPy.</p>
            <p className="about-links"><Link href="https://www.e-callisto.org/Data/data.html">e‑CALLISTO archive</Link><Link href="https://astrodoncel.uah.es/dashboard/">AstroDoncel portal</Link></p>
          </div>
        </section>

        <section className="about-row">
          <h2>Burst detector</h2>
          <div>
            <p>A YOLO11 model detects and classifies type II, III, IIIs, IV and V bursts. It was trained on the labelled
              e‑CALLISTO dataset of Wang et al. (2025, ApJS). Types IV and V are experimental because they have few
              training examples.</p>          </div>
        </section>

        <section className="about-row">
          <h2>Methods</h2>
          <div>
            <p>Type II shock heights and speeds use the Newkirk (1961) coronal density model; band-splitting follows
              Vršnak et al. (2002). Both depend on the density model and are shown as estimates.</p>
          </div>
        </section>

        <section className="about-row">
          <h2>Acknowledgements</h2>
          <div>
            <p>The e‑CALLISTO FITS Analyzer and Burst_No_Burst by <strong>Sahan S. Liyanage</strong> were the reference
              for the processing, RFI mitigation and measurement tools, which were reimplemented and tested for this
              project.</p>
            <p className="about-links"><Link href="https://github.com/SaanDev/e-Callisto_FITS_Analyzer">e‑CALLISTO FITS Analyzer</Link><Link href="https://doi.org/10.1093/rasti/rzag056">Software article</Link></p>
          </div>
        </section>

        <section className="about-row">
          <h2>Software</h2>
          <div>
            <p>Built with FastAPI, Astropy, SunPy, NumPy, SciPy, SQLAlchemy, ONNX Runtime, React, Vite and Plotly.</p>
            <p className="about-links"><Link href={`${REPO}/blob/main/THIRD_PARTY_NOTICES.md`}>Third-party notices</Link></p>
          </div>
        </section>
      </div>
    </main>
  );
}
