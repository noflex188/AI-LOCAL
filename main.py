#!/usr/bin/env python3
import sys
import traceback
from colorama import Fore, Style, init as colorama_init
from agent import Agent
from context import get_context

colorama_init(autoreset=True)

BANNER = f"""
{Fore.CYAN}╔══════════════════════════════════════════════╗
║     AI Assistant — gemma4:26b  (local)      ║
║  create_file · run_command · web_search      ║
╚══════════════════════════════════════════════╝{Style.RESET_ALL}
{Fore.WHITE}Commandes : /memory  /reset  /reset-all  /quit{Style.RESET_ALL}
"""

HELP = f"""
{Fore.YELLOW}  /memory      {Style.RESET_ALL}— afficher les notes mémorisées
{Fore.YELLOW}  /reset       {Style.RESET_ALL}— effacer la conversation (garde les notes)
{Fore.YELLOW}  /reset-all   {Style.RESET_ALL}— effacer conversation + toutes les notes
{Fore.YELLOW}  /help        {Style.RESET_ALL}— afficher cette aide
{Fore.YELLOW}  /quit        {Style.RESET_ALL}— quitter
"""


def main():
    print(BANNER)
    ctx = get_context()
    print(Fore.WHITE
          + f"  Langue: {ctx['language']}  |  Pays: {ctx['country']}  |"
          + f"  TZ: {ctx['timezone']}  |  OS: {ctx['os']}"
          + Style.RESET_ALL)
    agent = Agent()

    while True:
        try:
            user_input = input(Fore.BLUE + "\nToi: " + Style.RESET_ALL).strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAu revoir !")
            sys.exit(0)

        if not user_input:
            continue

        low = user_input.lower()

        if low in ("/quit", "/exit", "quit", "exit"):
            print("Au revoir !")
            sys.exit(0)

        if low == "/help":
            print(HELP)
            continue

        if low == "/memory":
            agent.show_memory()
            continue

        if low == "/reset":
            agent.reset()
            continue

        if low == "/reset-all":
            confirm = input(Fore.RED + "Effacer toute la mémoire ? (oui/non) : " + Style.RESET_ALL).strip().lower()
            if confirm in ("oui", "o", "yes", "y"):
                agent.reset_memory()
            else:
                print("Annulé.")
            continue

        print(Fore.GREEN + "\nAssistant: " + Style.RESET_ALL, end="", flush=True)
        try:
            agent.chat(user_input)
        except Exception as e:
            print(Fore.RED + f"\n[ERREUR] {e}" + Style.RESET_ALL)
            traceback.print_exc()


if __name__ == "__main__":
    main()
