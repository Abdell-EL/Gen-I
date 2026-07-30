import { AlertTriangle } from "lucide-react";

export function ErrorState({ message, title = "Impossible de terminer l’action" }: { message: string; title?: string }) {
  return (
    <div className="error-state" role="alert">
      <AlertTriangle size={19} />
      <div>
        <strong>{title}</strong>
        <p>{message}</p>
      </div>
    </div>
  );
}
