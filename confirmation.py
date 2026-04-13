"""
Système de confirmation pour les actions sensibles de l'agent.
Le générateur SSE se bloque sur un threading.Event jusqu'à ce que
l'utilisateur approuve ou refuse depuis le frontend.
"""
import threading
import uuid

# Outils qui nécessitent une confirmation explicite
SENSITIVE_TOOLS = {"create_file", "delete_file", "run_command"}

# Labels lisibles pour la modale
TOOL_LABELS = {
    "create_file":  "Créer / écraser un fichier",
    "delete_file":  "Supprimer un fichier",
    "run_command":  "Exécuter une commande shell",
}


class ConfirmationManager:
    def __init__(self):
        self._pending: dict[str, dict] = {}

    def request(self, tool_name: str, args: dict) -> tuple[str, threading.Event]:
        """Crée une demande en attente. Retourne (id, event)."""
        cid   = uuid.uuid4().hex[:10]
        event = threading.Event()
        self._pending[cid] = {"event": event, "approved": False}
        return cid, event

    def resolve(self, cid: str, approved: bool) -> bool:
        """Appelé par le endpoint /confirm. Débloque le générateur."""
        if cid not in self._pending:
            return False
        self._pending[cid]["approved"] = approved
        self._pending[cid]["event"].set()
        return True

    def get_result(self, cid: str) -> bool:
        return self._pending.pop(cid, {}).get("approved", False)


# Instance globale partagée entre server.py et agent.py
confirm_manager = ConfirmationManager()
