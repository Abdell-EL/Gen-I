import {
  ArrowRight,
  Bot,
  CheckCircle2,
  FileSearch,
  Search,
  ShieldCheck,
} from "lucide-react";
import { Link } from "react-router-dom";

import { PublicNav } from "../components/layout/PublicNav";

export function LandingPage() {
  return (
    <div className="landing-page">
      <div className="landing-shell">
        <main>
          <section className="landing-stage" id="solution">
            <PublicNav />

            <div className="landing-hero">
              <div className="hero-copy-block">
                <p className="hero-kicker">Plateforme de connaissance opérationnelle</p>
                <h1>
                  Une base Genius Services
                  <br />
                  plus rapide,
                  <br />
                  plus fiable,
                  <br />
                  plus traçable<span className="accent-dot">.</span>
                </h1>
                <p>
                  Recherche sémantique, réponses sourcées et audit complet pour
                  les équipes opérationnelles.
                </p>
                <div className="hero-actions">
                  <Link className="button button-primary button-large" to="/signin">
                    Se connecter
                    <ArrowRight size={17} />
                  </Link>
                </div>
                <div className="trust-row">
                  <span><CheckCircle2 size={16} />Données maîtrisées</span>
                  <span><CheckCircle2 size={16} />Sources visibles</span>
                  <span><CheckCircle2 size={16} />Audit systématique</span>
                </div>
              </div>

              <div className="hero-product-preview" aria-label="Aperçu du produit">
                <div className="preview-window">
                  <div className="preview-window-bar">
                    <div className="preview-product-name">
                      <span className="preview-product-mark">F</span>
                      <span>Assistant Genius Services</span>
                    </div>
                    <span className="preview-live">Opérationnel</span>
                  </div>
                  <div className="preview-body">
                    <div className="preview-content">
                      <div className="preview-welcome">
                        <small>Question métier</small>
                        <strong>Rechercher dans la base de connaissance</strong>
                      </div>
                      <div className="preview-question">
                        <Search size={17} />
                        <span>Quel code utiliser pour un problème de regard ?</span>
                        <button type="button" aria-label="Envoyer la question">
                          <ArrowRight size={15} />
                        </button>
                      </div>
                      <div className="preview-answer">
                        <span className="preview-answer-icon">
                          <FileSearch size={17} />
                        </span>
                        <div>
                          <small>Réponse vérifiée</small>
                          <p>
                            La procédure applicable indique le code situation et
                            les étapes de clôture associées à l’intervention.
                          </p>
                          <div className="preview-evidence">
                            <span>Confiance élevée</span>
                            <span>5 sources</span>
                            <span>Audit #128</span>
                          </div>
                        </div>
                      </div>
                      <div className="preview-sources">
                        <span><b>01</b> Référentiel des codes situation</span>
                        <span><b>02</b> Procédure de clôture réseau</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="role-section" id="securite">
            <div className="section-intro">
              <p className="eyebrow">Accès par responsabilité</p>
              <h2>Une plateforme,<br />deux espaces de travail.</h2>
              <p>
                La connaissance pour les agents. La maîtrise opérationnelle
                pour les administrateurs.
              </p>
            </div>
            <div className="role-grid">
              <Link to="/signin?role=agent" className="role-card agent-card">
                <span className="role-index">01</span>
                <span className="role-icon"><Bot size={24} /></span>
                <div>
                  <p>Espace Agent</p>
                  <h3>Interroger la base et vérifier chaque réponse.</h3>
                  <span>Accéder à l’assistant <ArrowRight size={16} /></span>
                </div>
              </Link>
              <Link to="/signin?role=admin" className="role-card admin-card">
                <span className="role-index">02</span>
                <span className="role-icon"><ShieldCheck size={24} /></span>
                <div>
                  <p>Espace Admin</p>
                  <h3>Superviser la plateforme, les audits et les volumes.</h3>
                  <span>Ouvrir la console <ArrowRight size={16} /></span>
                </div>
              </Link>
            </div>
          </section>

          <section className="landing-cta">
            <span className="shooting-star star-one" aria-hidden="true" />
            <span className="shooting-star star-two" aria-hidden="true" />
            <div>
              <p className="eyebrow">Plateforme interne Genius Services</p>
              <h2>La bonne connaissance,<br />au bon moment.</h2>
              <p>Une assistance métier rapide, lisible et vérifiable.</p>
            </div>
            <Link className="button button-primary button-large" to="/signin">
              Ouvrir la plateforme
              <ArrowRight size={17} />
            </Link>
          </section>
        </main>

        <footer className="landing-footer">
          <span>© 2026 Sogetrel — Plateforme interne Genius Services</span>
          <span>FastAPI · PostgreSQL · Milvus</span>
        </footer>
      </div>
    </div>
  );
}
