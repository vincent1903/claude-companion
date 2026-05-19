# Claude Companion

Mini-fenêtre de chat avec Claude (API Anthropic) intégrée à la recherche GNOME.
Tape ta question dans la barre de recherche du Shell, valide, et la réponse
apparaît dans une petite fenêtre GTK4 — pensé comme un remplacement de la
Quick Window de Claude Desktop, inutilisable sous GNOME Wayland.

![capture](docs/screenshot.png)

## Fonctionnalités

- Provider de recherche GNOME (`org.gnome.Shell.SearchProvider2`)
- Streaming des réponses, rendu Markdown (gras, italique, code, listes, titres…)
- Sélection du modèle (Haiku 4.5 / Sonnet 4.6 / Opus 4.7)
- Thème clair / sombre / automatique
- Interface en FR / EN / DE / ES / IT (et la langue de réponse de Claude s'adapte)
- System prompt et `max_tokens` configurables
- Clé API stockée dans le trousseau GNOME via libsecret

## Prérequis

- Une distribution Linux récente avec GNOME 47+ (testé sur Fedora 44)
- `flatpak` et `flatpak-builder`
- Le runtime GNOME 50 (installé automatiquement par `flatpak-builder` si besoin)
- Une clé API Anthropic (à coller au premier lancement)

Sur Fedora :

```sh
sudo dnf install flatpak flatpak-builder
flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo
```

## Installation

```sh
git clone https://github.com/<your-user>/claude-companion.git
cd claude-companion
flatpak-builder --user --install --force-clean build-dir org.little_home.ClaudeCompanion.yml
```

Le build télécharge `anthropic` et `markdown-it-py` depuis PyPI au moment du
build (le flag `--share=network` est activé dans le manifest pour le module
Python). Compte ~2 minutes la première fois.

## Activation du provider de recherche

Flatpak désactive par défaut tous les providers de recherche exportés.
Une fois installé :

1. Déconnecte / reconnecte ta session (pour que `gnome-shell` redécouvre le `.search-provider.ini`)
2. **Paramètres → Recherche** → active « Claude Companion »

## Premier lancement

- Lance l'app (`flatpak run org.little_home.ClaudeCompanion` ou via la grille
  des applications)
- Colle ta clé `sk-ant-…` dans le dialogue qui apparaît : elle est stockée
  dans le trousseau GNOME (jamais sur disque en clair)
- Ouvre les préférences pour choisir thème / langue / modèle / system prompt

## Utilisation depuis la recherche

- Active la recherche GNOME (touche Super, puis tape)
- Tape ta question — elle apparaît avec le titre « Demander à Claude : … »
- `Entrée` ouvre la fenêtre et envoie directement le prompt

## Architecture

```
src/
├── window.py            # Fenêtre GTK4 principale, préférences, chat
├── provider.py          # Service D-Bus SearchProvider2
├── api.py               # Wrapper Anthropic (streaming, system prompt, langue)
├── keyring.py           # Lecture/écriture clé API via libsecret
├── markdown_render.py   # Rendu Markdown → Gtk.TextTag
├── config.py            # Config JSON (~/.config/claude-companion/)
└── i18n.py              # Setup gettext (locale dynamique)
bin/                     # Wrappers shell (flatpak entry points)
data/                    # .desktop, .metainfo.xml, .service, .ini, icône
po/                      # Traductions (.po) + template (.pot)
```

## Désinstallation

```sh
flatpak uninstall --user --delete-data org.little_home.ClaudeCompanion
```

## Licence

MIT — voir [LICENSE](LICENSE).
