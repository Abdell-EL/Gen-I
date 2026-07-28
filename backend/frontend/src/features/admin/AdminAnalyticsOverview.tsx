import { BarChart3, CircleUserRound, MessageCircleQuestion, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";

import { ErrorState } from "../../components/ui/ErrorState";
import { LoadingState } from "../../components/ui/LoadingState";
import { getAdminErrorMessage, getQuestionAnalytics, getUserAnalytics } from "../../services/adminApi";

export function AdminAnalyticsOverview({ refreshKey }: { refreshKey: number }) {
  const [users, setUsers] = useState<Awaited<ReturnType<typeof getUserAnalytics>> | null>(null);
  const [questions, setQuestions] = useState<Awaited<ReturnType<typeof getQuestionAnalytics>> | null>(null);
  const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError(null);
      void Promise.all([
        getUserAnalytics({ page: 1, page_size: 25 }),
        getQuestionAnalytics({ limit: 20 }),
      ])
        .then(([userData, questionData]) => {
          if (active) {
            setUsers(userData);
            setQuestions(questionData);
          }
        })
        .catch((requestError) => {
          if (active) setError(getAdminErrorMessage(requestError));
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [refreshKey]);
  if (loading) return <LoadingState label="Chargement de l’aperçu d’activité…" />;
  if (error) return <ErrorState message={error} />;
  if (!users || !questions) return null;
  const loadedActive = users.items.filter((item) => item.is_active).length;
  const loadedQuestionTotal = users.items.reduce((sum, item) => sum + item.questions_count, 0);
  const loadedContributors = users.items.filter((item) => item.questions_count > 0).length;
  const topUser = users.items[0]; const topQuestion = questions.items[0];
  return <section className="admin-insights-overview"><div className="admin-panel-heading"><div><span className="section-kicker">Aperçu analytique</span><h2>Activité récente disponible</h2><p>Les valeurs marquées « page chargée » portent sur les 25 utilisateurs actuellement chargés.</p></div></div><div className="admin-insight-grid"><article><UsersRound size={20} /><span>Total utilisateurs</span><strong>{users.total}</strong><small>Global, selon les filtres par défaut</small></article><article><CircleUserRound size={20} /><span>Utilisateurs actifs</span><strong>{loadedActive}</strong><small>Sur la page chargée</small></article><article><MessageCircleQuestion size={20} /><span>Questions comptabilisées</span><strong>{loadedQuestionTotal}</strong><small>Utilisateurs de la page chargée</small></article><article><BarChart3 size={20} /><span>Utilisateurs contributeurs</span><strong>{loadedContributors}</strong><small>Sur la page chargée</small></article></div><div className="admin-highlight-grid"><article><span>Utilisateur le plus actif</span><strong>{topUser?.full_name ?? "Aucune activité"}</strong><small>{topUser ? `${topUser.questions_count} question(s)` : "—"}</small></article><article><span>Question la plus fréquente</span><strong>{topQuestion?.question ?? "Aucune question"}</strong><small>{topQuestion ? `${topQuestion.count} occurrence(s)` : "—"}</small></article></div></section>;
}
