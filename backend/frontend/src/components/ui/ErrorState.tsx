import { AlertTriangle } from "lucide-react";

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="error-state" role="alert">
      <AlertTriangle size={19} />
      <div>
        <strong>Impossible de terminer l’action</strong>
        <p>{message}</p>
      </div>
    </div>
  );
}
