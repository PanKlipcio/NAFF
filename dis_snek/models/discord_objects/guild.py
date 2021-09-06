import base64

from dis_snek.models.enums import (
    NSFWLevels,
    SystemChannelFlags,
    VerificationLevels,
    DefaultNotificationLevels,
    ExplicitContentFilterLevels,
    MFALevels,
    ChannelTypes,
)
from dis_snek.utils.serializer import to_image_data, dict_filter_none
from dis_snek.utils.converters import timestamp_converter
from functools import partial
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Dict, List, Optional, Union

import attr
import inspect
from attr.converters import optional
from dis_snek.models.discord import DiscordObject
from dis_snek.models.discord_objects.emoji import CustomEmoji
from dis_snek.utils.attr_utils import define
from dis_snek.utils.proxy import CacheView, CacheProxy
from dis_snek.models.discord_objects.channel import BaseChannel

if TYPE_CHECKING:
    from io import IOBase
    from pathlib import Path

    from dis_snek.models.discord_objects.channel import TYPE_GUILD_CHANNEL, Thread, GuildCategory
    from dis_snek.models.discord_objects.role import Role
    from dis_snek.models.discord_objects.user import Member
    from dis_snek.models.snowflake import Snowflake_Type


@define()
class Guild(DiscordObject):
    unavailable: bool = attr.ib(default=False)
    name: str = attr.ib()
    _icon: Optional[str] = attr.ib(default=None)  # todo merge, convert to asset
    _icon_hash: Optional[str] = attr.ib(default=None)
    splash: Optional[str] = attr.ib(default=None)
    discovery_splash: Optional[str] = attr.ib(default=None)
    # owner: bool = attr.ib(default=False)  # we get this from api but it's kinda useless to store
    permissions: Optional[str] = attr.ib(default=None)  # todo convert to permissions obj
    afk_channel_id: Optional["Snowflake_Type"] = attr.ib(default=None)
    afk_timeout: Optional[int] = attr.ib(default=None)
    widget_enabled: bool = attr.ib(default=False)
    widget_channel_id: Optional["Snowflake_Type"] = attr.ib(default=None)
    verification_level: Union[VerificationLevels, int] = attr.ib(default=VerificationLevels.NONE)
    default_message_notifications: Union[DefaultNotificationLevels, int] = attr.ib(
        default=DefaultNotificationLevels.ALL_MESSAGES
    )
    explicit_content_filter: Union[ExplicitContentFilterLevels, int] = attr.ib(
        default=ExplicitContentFilterLevels.DISABLED
    )
    _emojis: List[dict] = attr.ib(factory=list)
    _features: List[str] = attr.ib(factory=list)
    mfa_level: Union[MFALevels, int] = attr.ib(default=MFALevels.NONE)
    system_channel_id: Optional["Snowflake_Type"] = attr.ib(default=None)
    system_channel_flags: Union[SystemChannelFlags, int] = attr.ib(default=SystemChannelFlags.NONE)
    rules_channel_id: Optional["Snowflake_Type"] = attr.ib(default=None)
    joined_at: str = attr.ib(default=None, converter=optional(timestamp_converter))
    large: bool = attr.ib(default=False)
    member_count: int = attr.ib(default=0)
    voice_states: List[dict] = attr.ib(factory=list)
    presences: List[dict] = attr.ib(factory=list)
    max_presences: Optional[int] = attr.ib(default=None)
    max_members: Optional[int] = attr.ib(default=None)
    vanity_url_code: Optional[str] = attr.ib(default=None)
    description: Optional[str] = attr.ib(default=None)
    banner: Optional[str] = attr.ib(default=None)
    premium_tier: Optional[str] = attr.ib(default=None)
    premium_subscription_count: int = attr.ib(default=0)
    preferred_locale: str = attr.ib()
    public_updates_channel_id: Optional["Snowflake_Type"] = attr.ib(default=None)
    max_video_channel_users: int = attr.ib(default=0)
    welcome_screen: Optional[dict] = attr.ib(factory=list)
    nsfw_level: Union[NSFWLevels, int] = attr.ib(default=NSFWLevels.DEFAULT)
    stage_instances: List[dict] = attr.ib(factory=list)
    stickers: List[dict] = attr.ib(factory=list)

    _owner_id: "Snowflake_Type" = attr.ib()
    _channel_ids: List["Snowflake_Type"] = attr.ib(factory=list)
    _thread_ids: List["Snowflake_Type"] = attr.ib(factory=list)
    _member_ids: List["Snowflake_Type"] = attr.ib(factory=list)
    _role_ids: List["Snowflake_Type"] = attr.ib(factory=list)

    @classmethod
    def process_dict(cls, data, client):
        guild_id = data["id"]

        channels_data = data.pop("channels", [])
        data["channel_ids"] = [client.cache.place_channel_data(channel_data).id for channel_data in channels_data]

        threads_data = data.pop("threads", [])
        data["thread_ids"] = [client.cache.place_channel_data(thread_data).id for thread_data in threads_data]

        members_data = data.pop("members", [])
        data["member_ids"] = [client.cache.place_member_data(guild_id, member_data).id for member_data in members_data]

        roles_data = data.pop("roles", [])
        data["role_ids"] = list(client.cache.place_role_data(guild_id, roles_data).keys())

        return data

    @property
    def channels(
        self,
    ) -> Union[CacheView, Awaitable[Dict["Snowflake_Type", "TYPE_GUILD_CHANNEL"]], AsyncIterator["TYPE_GUILD_CHANNEL"]]:
        return CacheView(ids=self._channel_ids, method=self._client.cache.get_channel)

    @property
    def threads(self) -> Union[CacheView, Awaitable[Dict["Snowflake_Type", "Thread"]], AsyncIterator["Thread"]]:
        return CacheView(ids=self._thread_ids, method=self._client.cache.get_channel)

    @property
    def members(self) -> Union[CacheView, Awaitable[Dict["Snowflake_Type", "Member"]], AsyncIterator["Member"]]:
        return CacheView(ids=self._member_ids, method=partial(self._client.cache.get_member, self.id))

    @property
    def roles(self) -> Union[CacheView, Awaitable[Dict["Snowflake_Type", "Role"]], AsyncIterator["Role"]]:
        return CacheView(ids=self._role_ids, method=partial(self._client.cache.get_role, self.id))

    @property
    def me(self) -> Union[CacheProxy, Awaitable["Member"], "Member"]:
        return CacheProxy(id=self._client.user.id, method=partial(self._client.cache.get_member, self.id))

    @property
    def owner(self) -> Union[CacheProxy, Awaitable["Member"], "Member"]:
        return CacheProxy(id=self._owner_id, method=partial(self._client.cache.get_member, self.id))

    def is_owner(self, member: "Member") -> bool:
        return self._owner_id == member.id

    # @property
    # def
    # if not self.member_count and "approximate_member_count" in data:
    #     self.member_count = data.get("approximate_member_count", 0)

    async def create_custom_emoji(
        self,
        name: str,
        imagefile: Union[str, "Path", "IOBase"],
        roles: Optional[List[Union["Snowflake_Type", "Role"]]] = None,
        reason: Optional[str] = None,
    ) -> "CustomEmoji":
        data_payload = dict_filter_none(
            dict(
                name=name,
                image=to_image_data(imagefile),
                roles=roles,
            )
        )

        emoji_data = await self._client.http.create_guild_emoji(data_payload, self.id, reason=reason)
        emoji_data["guild_id"] = self.id
        return CustomEmoji.from_dict(emoji_data, self._client)  # TODO Probably cache it

    async def get_all_custom_emojis(self) -> List[CustomEmoji]:
        emojis_data = await self._client.http.get_all_guild_emoji(self.id)
        return [CustomEmoji.from_dict(emoji_data, self._client) for emoji_data in emojis_data]

    async def get_custom_emoji(self, emoji_id: "Snowflake_Type") -> CustomEmoji:
        emoji_data = await self._client.http.get_guild_emoji(self.id, emoji_id)
        return CustomEmoji.from_dict(emoji_data, self._client)

    async def create_channel(
        self,
        channel_type: ChannelTypes,
        name: str,
        topic: str = "",
        position=0,
        permission_overwrites: dict = None,
        category: Union["Snowflake_Type", "GuildCategory"] = None,
        nsfw: bool = False,
        bitrate=64000,
        user_limit: int = 0,
        slowmode_delay=0,
        reason: str = None,
    ) -> "BaseChannel":
        """
        Create a guild channel, allows for explicit channel type setting.

        :param channel_type: The type of channel to create
        :param name: The name of the channel
        :param topic: The topic of the channel
        :param position: The position of the channel in the channel list
        :param permission_overwrites: Permission overwrites to apply to the channel
        :param category: The category this channel should be within
        :param nsfw: Should this channel be marked nsfw
        :param bitrate: The bitrate of this channel, only for voice
        :param user_limit: The max users that can be in this channel, only for voice
        :param slowmode_delay: The time users must wait between sending messages
        :param reason: The reason for creating this channel
        """
        if category and hasattr(category, "id"):
            category = category.id

        _channel = await self._client.http.create_guild_channel(
            self.id,
            name,
            channel_type,
            topic,
            position,
            permission_overwrites,
            category,
            nsfw,
            bitrate,
            user_limit,
            slowmode_delay,
            reason,
        )
        return BaseChannel.from_dict_factory(_channel, self._client)

    async def create_text_channel(
        self,
        name: str,
        topic: str = "",
        position=0,
        permission_overwrites: dict = None,
        category: Union["Snowflake_Type", "GuildCategory"] = None,
        nsfw: bool = False,
        slowmode_delay=0,
        reason: str = None,
    ):
        """
        Create a text channel in this guild.

        :param name: The name of the channel
        :param topic: The topic of the channel
        :param position: The position of the channel in the channel list
        :param permission_overwrites: Permission overwrites to apply to the channel
        :param category: The category this channel should be within
        :param nsfw: Should this channel be marked nsfw
        :param slowmode_delay: The time users must wait between sending messages
        :param reason: The reason for creating this channel
        """
        return await self.create_channel(
            channel_type=ChannelTypes.GUILD_TEXT,
            name=name,
            topic=topic,
            position=position,
            permission_overwrites=permission_overwrites,
            category=category,
            nsfw=nsfw,
            slowmode_delay=slowmode_delay,
            reason=reason,
        )

    async def create_voice_channel(
        self,
        name: str,
        topic: str = "",
        position=0,
        permission_overwrites: dict = None,
        category: Union["Snowflake_Type", "GuildCategory"] = None,
        nsfw: bool = False,
        bitrate=64000,
        user_limit: int = 0,
        reason: str = None,
    ):
        """
        Create a guild voice channel

        :param name: The name of the channel
        :param topic: The topic of the channel
        :param position: The position of the channel in the channel list
        :param permission_overwrites: Permission overwrites to apply to the channel
        :param category: The category this channel should be within
        :param nsfw: Should this channel be marked nsfw
        :param bitrate: The bitrate of this channel, only for voice
        :param user_limit: The max users that can be in this channel, only for voice
        :param reason: The reason for creating this channel
        """
        return await self.create_channel(
            channel_type=ChannelTypes.GUILD_VOICE,
            name=name,
            topic=topic,
            position=position,
            permission_overwrites=permission_overwrites,
            category=category,
            nsfw=nsfw,
            bitrate=bitrate,
            user_limit=user_limit,
            reason=reason,
        )

    async def create_stage_channel(
        self,
        name: str,
        topic: str = "",
        position=0,
        permission_overwrites: dict = None,
        category: Union["Snowflake_Type", "GuildCategory"] = None,
        bitrate=64000,
        user_limit: int = 0,
        reason: str = None,
    ):
        """
        Create a guild stage channel

        :param name: The name of the channel
        :param topic: The topic of the channel
        :param position: The position of the channel in the channel list
        :param permission_overwrites: Permission overwrites to apply to the channel
        :param category: The category this channel should be within
        :param bitrate: The bitrate of this channel, only for voice
        :param user_limit: The max users that can be in this channel, only for voice
        :param reason: The reason for creating this channel
        """
        return await self.create_channel(
            channel_type=ChannelTypes.GUILD_STAGE_VOICE,
            name=name,
            topic=topic,
            position=position,
            permission_overwrites=permission_overwrites,
            category=category,
            bitrate=bitrate,
            user_limit=user_limit,
            reason=reason,
        )

    async def create_category(
        self,
        name: str,
        position=0,
        permission_overwrites: dict = None,
        reason: str = None,
    ):
        """
        Create a category within this guild

        :param name: The name of the channel
        :param position: The position of the channel in the channel list
        :param permission_overwrites: Permission overwrites to apply to the channel
        :param reason: The reason for creating this channel
        """
        return await self.create_channel(
            channel_type=ChannelTypes.GUILD_CATEGORY,
            name=name,
            position=position,
            permission_overwrites=permission_overwrites,
            reason=reason,
        )
