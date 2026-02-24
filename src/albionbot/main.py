import logging
import nextcord
from nextcord.ext import commands
from dotenv import load_dotenv

from .config import load_config
from .storage.store import Store
from .modules.raids import RaidModule
from .modules.bank import BankModule

log = logging.getLogger("albionbot")

def build_bot() -> commands.Bot:
    intents = nextcord.Intents.default()
    intents.guilds = True
    intents.members = True
    intents.voice_states = True
    # If DM wizard doesn't capture messages, enable Message Content Intent in the portal and uncomment:
    # intents.message_content = True
    return commands.Bot(intents=intents)

def main():
    load_dotenv()
    cfg = load_config()
    store = Store(cfg.data_path, bank_action_log_limit=500, bank_database_url=cfg.bank_database_url, bank_sqlite_path=cfg.bank_sqlite_path)
    bot = build_bot()

    raids = RaidModule(bot, store, cfg)
    bank = BankModule(bot, store, cfg)

    @bot.event
    async def on_ready():
        log.info("Logged in as %s", bot.user)

        raids.start()

        # persistent views for existing raids after restart
        for raid in list(store.raids.values()):
            if raid.message_id:
                tpl = store.templates.get(raid.template_name)
                if not tpl:
                    continue
                view = raids.build_view(raid, tpl)
                try:
                    bot.add_view(view, message_id=raid.message_id)
                except Exception:
                    try:
                        bot.add_view(view)
                    except Exception:
                        pass

    bot.run(cfg.discord_token)
