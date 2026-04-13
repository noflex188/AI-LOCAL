# AI Assistant — Local

Assistant IA personnel tournant entièrement en local grâce à [Ollama](https://ollama.com).  
Aucune donnée ne quitte ta machine.

## Fonctionnalités

- Chat avec un LLM local (gemma4:26b ou gemma4:e4b)
- Recherche web via DuckDuckGo
- Lecture et modification de fichiers, exécution de commandes
- Gestion de projets avec explorateur de fichiers et indexation RAG
- Notes vocales avec génération de rapport
- Mémoire persistante entre les conversations
- Interface accessible sur le réseau local (mobile, tablette)

## Installation

```bash
git clone https://github.com/noflex188/AI-LOCAL.git
cd AI-LOCAL
install.bat
```

Le script installe automatiquement Python et Ollama s'ils sont absents, puis configure l'environnement et télécharge le modèle choisi.

**Prérequis :** Windows 10/11, 8 Go de RAM minimum (16 Go recommandé pour gemma4:26b)

## Mise à jour

```bash
update.bat
```

Récupère les dernières modifications sans toucher à tes données personnelles (conversations, notes, mémoire).

## Démarrage

```
start_web.bat
```

Ouvre ensuite `http://localhost:8000` dans ton navigateur.  
Accessible depuis un téléphone ou une tablette via `http://<IP-locale>:8000`.

## Modèles supportés

| Modèle | Taille | RAM requise |
|---|---|---|
| gemma4:26b | ~17 GB | 16+ GB |
| gemma4:e4b | ~3 GB | 4+ GB |

## Stack technique

- **Backend** : Python, FastAPI, Ollama
- **Frontend** : HTML/CSS/JS vanilla
- **RAG** : embeddings nomic-embed-text, similarité cosinus
- **Recherche** : DuckDuckGo (sans clé API)
