import asyncio
import datetime as dt
import json
import logging

import aiohttp
import mystbin
import asyncpg
import discord
import toml
from asyncdagpi import Client
from discord.ext import commands, ipc

from utils.CustomContext import PenguinContext

STARTUP_EXTENSIONS = ['cogs.members', 'cogs.owner', 'cogs.moderator', 'cogs.fun', "jishaku", "cogs.mute",
                      'cogs.animals', 'listeners.listener', 'cogs.help_command', 'cogs.images',
                      'cogs.settings', 'cogs.checks',
                      'listeners.errors', 'listeners.guilds', 'listeners.moderation',
                      'listeners.reactionroles', 'listeners.welcomer', 'listeners.logging']

intents = discord.Intents.default()
intents.members = True

async def get_prefix(bot, message: discord.Message):
    prefix = 'p,'
    
    if not message.guild:
        return commands.when_mentioned_or(*prefix)(bot, message)

    else:
        if bot.cache[message.guild.id]['prefix']:
            return commands.when_mentioned_or(bot.cache[message.guild.id]['prefix'])(bot, message)
        elif not bot.cache[message.guild.id]['prefix']:
            return commands.when_mentioned_or(*prefix)(bot, message)


class PenguinBot(commands.AutoShardedBot):
    async def get_context(self, message, *, cls=None):
        return await super().get_context(message, cls=cls or PenguinContext)

    def __init__(self, *args, **kwargs):
        super().__init__(get_prefix,
                         description = "A moderation / fun bot",
                        intents = intents,
                         allowed_mentions = discord.AllowedMentions.none(),
                         activity=discord.Activity(
                             type=discord.ActivityType.listening, name="@Penguin"),
                         owner_ids = {447422100798570496},
                         **kwargs)

        self._logger = logging.getLogger(__name__)

        self.loop = asyncio.get_event_loop()
        self.session = aiohttp.ClientSession()

        self.start_time = dt.datetime.now()

        with open("config.json") as res:
            self.config = json.load(res)

        self.ipc = ipc.Server(self, "localhost", self.config['ipc-port'], self.config['ipc-key'])
        self.load_extension("utils.ipc")

        self.db = self.loop.run_until_complete(
            asyncpg.create_pool(
               **self.config['db']
            )
        )

        # Cache stuff
        self.stats = {}
        self.prefixes = {}
        self.cache = {}
        self.disabledCommands = []
        self.blacklistedUsers = []
        self.reactionRoleDict = self.loop.run_until_complete(
            self.cache_reactionroles())

        records = self.loop.run_until_complete(
            self.db.fetch("SELECT * FROM blacklist"))
        for i in records:
            self.blacklistedUsers.append(i["id"])

        records = self.loop.run_until_complete(
            self.db.fetch("SELECT * FROM guild_config"))
        self.prefixes = dict(self.loop.run_until_complete(
            self.db.fetch("SELECT id, prefix FROM guild_config")))

        for record in records:
            d = self.refresh_template(record)
            self.cache.update(d)

        self.get_announcement()
        self.dagpi_client = Client(self.config['dagpi'])
        self.command_stats = {}
        self.mystbin = mystbin.Client()

        self.load_cogs()

    async def on_ipc_ready(self):
        print("ipc ready")

    def refresh_template(self, record: asyncpg.Record):
        d = {
            record["id"]: {"prefix": record["prefix"], "autorole": record["autorole"],
                           "welcomeMessage": record["welcomemessage"], "welcomeEnabled": record["welcomeenabled"],
                           "welcomeId": record["welcomeid"], "logId": record['log_id']}
        }
        return d

    async def on_ready(self):
        print(
            "Logged in! \n"
            f"{'-' * 20}\n"
            f"Bot Name: {self.user} \n"
            f"Bot ID: {self.user.id} \n"
            f"{'-' * 20}"
        )

    async def refresh_cache(self):
        records = await self.db.fetch("SELECT * FROM guild_config")
        for record in records:
            d = self.refresh_template(record)
            self.cache.update(d)

    async def cache_reactionroles(self):
        return dict(await self.db.fetch("SELECT msg_id, role_id FROM reaction_roles"))

    async def refresh_blacklist(self):
        records = await self.db.fetch("SELECT * FROM blacklist")
        self.blacklistedUsers = []
        for i in records:
            self.blacklistedUsers.append(i["id"])

    async def refresh_connection(self):
        await self.db.close()
        self.db = await asyncpg.connect(user=self.config['default']['db_user'],
                                        password=self.config['default']['db_password'],
                                        database=self.config['default']['db_name'], host='127.0.0.1')

    async def refresh_cache_for(self, guildId):
        record = await self.db.fetchrow("SELECT * FROM guild_config WHERE id = $1", guildId)
        self.cache.update(self.refresh_template(record))

    def get_announcement(self):
        with open('announcement.txt', 'r') as file:
            self.announcement = file.read()

    def load_cogs(self):
        logger = logging.getLogger("cogs")

        for extension in STARTUP_EXTENSIONS:
            try:
                self.load_extension(extension)
                logger.info(f"Loaded extension {extension}")
            except Exception as e:
                exc = '{}: {}'.format(type(e).__name__, e)
                logger.error('Failed to load extension {}\n{}'.format(extension, exc))
