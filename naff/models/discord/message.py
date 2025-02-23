import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, List, Optional, Sequence, Union, Mapping

import naff.models as models
from naff.client.const import GUILD_WELCOME_MESSAGES, MISSING, Absent
from naff.client.errors import EphemeralEditException, ThreadOutsideOfGuild
from naff.client.mixins.serialization import DictSerializationMixin
from naff.client.utils.attr_utils import define, field
from naff.client.utils.attr_converters import optional as optional_c
from naff.client.utils.attr_converters import timestamp_converter
from naff.client.utils.serializer import dict_filter_none
from naff.models.discord.file import UPLOADABLE_TYPE
from .base import DiscordObject
from .enums import (
    ChannelTypes,
    InteractionTypes,
    MentionTypes,
    MessageActivityTypes,
    MessageFlags,
    MessageTypes,
    AutoArchiveDuration,
)
from .snowflake import to_snowflake, Snowflake_Type, to_snowflake_list, to_optional_snowflake
from naff.models.discord.channel import BaseChannel

if TYPE_CHECKING:
    from naff.client import Client

__all__ = (
    "Attachment",
    "ChannelMention",
    "MessageActivity",
    "MessageReference",
    "MessageInteraction",
    "AllowedMentions",
    "BaseMessage",
    "Message",
    "MessageTypes",
    "process_allowed_mentions",
    "process_message_reference",
    "process_message_payload",
)

channel_mention = re.compile(r"<#(?P<id>[0-9]{17,})>")


@define()
class Attachment(DiscordObject):
    filename: str = field()
    """name of file attached"""
    description: Optional[str] = field(default=None)
    """description for the file"""
    content_type: Optional[str] = field(default=None)
    """the attachment's media type"""
    size: int = field()
    """size of file in bytes"""
    url: str = field()
    """source url of file"""
    proxy_url: str = field()
    """a proxied url of file"""
    height: Optional[int] = field(default=None)
    """height of file (if image)"""
    width: Optional[int] = field(default=None)
    """width of file (if image)"""
    ephemeral: bool = field(default=False)
    """whether this attachment is ephemeral"""

    @property
    def resolution(self) -> tuple[Optional[int], Optional[int]]:
        """Returns the image resolution of the attachment file"""
        return self.height, self.width


@define()
class ChannelMention(DiscordObject):
    guild_id: "Snowflake_Type" = field()
    """id of the guild containing the channel"""
    type: ChannelTypes = field(converter=ChannelTypes)
    """the type of channel"""
    name: str = field()
    """the name of the channel"""


@dataclass
class MessageActivity:
    type: MessageActivityTypes
    """type of message activity"""
    party_id: str = None
    """party_id from a Rich Presence event"""


@define()
class MessageReference(DictSerializationMixin):
    """
    Reference to an originating message.

    Can be used for replies.

    """

    message_id: int = field(default=None, converter=optional_c(to_snowflake))
    """id of the originating message."""
    channel_id: Optional[int] = field(default=None, converter=optional_c(to_snowflake))
    """id of the originating message's channel."""
    guild_id: Optional[int] = field(default=None, converter=optional_c(to_snowflake))
    """id of the originating message's guild."""
    fail_if_not_exists: bool = field(default=True)
    """When sending a message, whether to error if the referenced message doesn't exist instead of sending as a normal (non-reply) message, default true."""

    @classmethod
    def for_message(cls, message: "Message", fail_if_not_exists: bool = True) -> "MessageReference":
        """
        Creates a reference to a message.

        parameters
            message: The target message to reference.
            fail_if_not_exists: Whether to error if the referenced message doesn't exist instead of sending as a normal (non-reply) message

        Returns:
            A MessageReference object.

        """
        return cls(
            message_id=message.id,
            channel_id=message._channel_id,
            guild_id=message._guild_id,
            fail_if_not_exists=fail_if_not_exists,
        )


@define()
class MessageInteraction(DiscordObject):
    type: InteractionTypes = field(converter=InteractionTypes)
    """the type of interaction"""
    name: str = field()
    """the name of the application command"""

    _user_id: "Snowflake_Type" = field()

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        user_data = data["user"]
        data["user_id"] = client.cache.place_user_data(user_data).id
        return data

    async def user(self) -> "models.User":
        """Get the user associated with this interaction."""
        return await self.get_user(self._user_id)


@define(kw_only=False)
class AllowedMentions(DictSerializationMixin):
    """
    The allowed mention field allows for more granular control over mentions without various hacks to the message content.

    This will always validate against message content to avoid phantom
    pings, and check against user/bot permissions.

    """

    parse: Optional[List[str]] = field(factory=list)
    """An array of allowed mention types to parse from the content."""
    roles: Optional[List["Snowflake_Type"]] = field(factory=list, converter=to_snowflake_list)
    """Array of role_ids to mention. (Max size of 100)"""
    users: Optional[List["Snowflake_Type"]] = field(factory=list, converter=to_snowflake_list)
    """Array of user_ids to mention. (Max size of 100)"""
    replied_user = field(default=False)
    """For replies, whether to mention the author of the message being replied to. (default false)"""

    def add_parse(self, *mention_types: Union["MentionTypes", str]) -> None:
        """
        Add a mention type to the list of allowed mentions to parse.

        Args:
            *mention_types: The types of mentions to add

        """
        for mention_type in mention_types:
            if not isinstance(mention_type, MentionTypes) and mention_type not in MentionTypes.__members__.values():
                raise ValueError(f"Invalid mention type: {mention_type}")
            self.parse.append(mention_type)

    def add_roles(self, *roles: Union["models.Role", "Snowflake_Type"]) -> None:
        """
        Add roles that are allowed to be mentioned.

        Args:
            *roles: The roles to add

        """
        for role in roles:
            self.roles.append(to_snowflake(role))

    def add_users(self, *users: Union["models.Member", "models.BaseUser", "Snowflake_Type"]) -> None:
        """
        Add users that are allowed to be mentioned.

        Args:
            *users: The users to add

        """
        for user in users:
            self.users.append(to_snowflake(user))

    @classmethod
    def all(cls) -> "AllowedMentions":
        """
        Allows every user and role to be mentioned.

        Returns:
            An AllowedMentions object

        """
        return cls(parse=list(MentionTypes.__members__.values()), replied_user=True)

    @classmethod
    def none(cls) -> "AllowedMentions":
        """
        Disallows any user or role to be mentioned.

        Returns:
            An AllowedMentions object

        """
        return cls()


@define()
class BaseMessage(DiscordObject):
    _channel_id: "Snowflake_Type" = field(default=MISSING, converter=to_optional_snowflake)
    _thread_channel_id: Optional["Snowflake_Type"] = field(default=None, converter=to_optional_snowflake)
    _guild_id: Optional["Snowflake_Type"] = field(default=None, converter=to_optional_snowflake)
    _author_id: "Snowflake_Type" = field(default=MISSING, converter=to_optional_snowflake)

    @property
    def guild(self) -> "models.Guild":
        """The guild the message was sent in"""
        return self._client.cache.get_guild(self._guild_id)

    @property
    def channel(self) -> "models.TYPE_MESSAGEABLE_CHANNEL":
        """The channel the message was sent in"""
        channel = self._client.cache.get_channel(self._channel_id)

        if not self._guild_id and not channel:
            # allow dm operations without fetching a dm channel from API
            channel = BaseChannel.from_dict_factory({"id": self._channel_id, "type": ChannelTypes.DM}, self._client)
            if self.author:
                channel.recipients = [self.author]
        return channel

    @property
    def thread(self) -> "models.TYPE_THREAD_CHANNEL":
        """The thread that was started from this message, includes thread member object"""
        return self._client.cache.get_channel(self._thread_channel_id)

    @property
    def author(self) -> Union["models.Member", "models.User"]:
        """The author of this message. Only a valid user in the case where the message is generated by a user or bot user."""
        if self._author_id:
            member = None
            if self._guild_id:
                member = self._client.cache.get_member(self._guild_id, self._author_id)
            return member or self._client.cache.get_user(self._author_id)
        return MISSING


@define()
class Message(BaseMessage):
    content: str = field(default=MISSING)
    """Contents of the message"""
    timestamp: "models.Timestamp" = field(default=MISSING, converter=optional_c(timestamp_converter))
    """When this message was sent"""
    edited_timestamp: Optional["models.Timestamp"] = field(default=None, converter=optional_c(timestamp_converter))
    """When this message was edited (or `None` if never)"""
    tts: bool = field(default=False)
    """Whether this was a TTS message"""
    mention_everyone: bool = field(default=False)
    """Whether this message mentions everyone"""
    mention_channels: List[ChannelMention] = field(factory=list)
    """Channels specifically mentioned in this message"""
    attachments: List[Attachment] = field(factory=list)
    """Any attached files"""
    embeds: List["models.Embed"] = field(factory=list)
    """Any embedded content"""
    reactions: List["models.Reaction"] = field(factory=list)
    """Reactions to the message"""
    nonce: Optional[Union[int, str]] = field(default=None)
    """Used for validating a message was sent"""
    pinned: bool = field(default=False)
    """Whether this message is pinned"""
    webhook_id: Optional["Snowflake_Type"] = field(default=None, converter=to_optional_snowflake)
    """If the message is generated by a webhook, this is the webhook's id"""
    type: MessageTypes = field(default=MISSING, converter=optional_c(MessageTypes))
    """Type of message"""
    activity: Optional[MessageActivity] = field(default=None, converter=optional_c(MessageActivity))
    """Activity sent with Rich Presence-related chat embeds"""
    application: Optional["models.Application"] = field(default=None)  # TODO: partial application
    """Application sent with Rich Presence-related chat embeds"""
    application_id: Optional["Snowflake_Type"] = field(default=None, converter=to_optional_snowflake)
    """If the message is an Interaction or application-owned webhook, this is the id of the application"""
    message_reference: Optional[MessageReference] = field(
        default=None, converter=optional_c(MessageReference.from_dict)
    )
    """Data showing the source of a crosspost, channel follow add, pin, or reply message"""
    flags: MessageFlags = field(default=MessageFlags.NONE, converter=MessageFlags)
    """Message flags combined as a bitfield"""
    interaction: Optional["MessageInteraction"] = field(default=None)
    """Sent if the message is a response to an Interaction"""
    components: Optional[List["models.ActionRow"]] = field(default=None)
    """Sent if the message contains components like buttons, action rows, or other interactive components"""
    sticker_items: Optional[List["models.StickerItem"]] = field(default=None)
    """Sent if the message contains stickers"""
    _mention_ids: List["Snowflake_Type"] = field(factory=list)
    _mention_roles: List["Snowflake_Type"] = field(factory=list)
    _referenced_message_id: Optional["Snowflake_Type"] = field(default=None)

    @property
    async def mention_users(self) -> AsyncGenerator["models.Member", None]:
        """A generator of users mentioned in this message"""
        for u_id in self._mention_ids:
            yield await self._client.cache.fetch_member(self._guild_id, u_id)

    @property
    async def mention_roles(self) -> AsyncGenerator["models.Role", None]:
        """A generator of roles mentioned in this message"""
        for r_id in self._mention_roles:
            yield await self._client.cache.fetch_role(self._guild_id, r_id)

    @property
    def thread(self) -> "models.TYPE_THREAD_CHANNEL":
        """The thread that was started from this message, if any"""
        return self._client.cache.get_channel(self.id)

    async def fetch_referenced_message(self) -> Optional["Message"]:
        """
        Fetch the message this message is referencing, if any.

        Returns:
            The referenced message, if found

        """
        if self._referenced_message_id is None:
            return None
        return await self._client.cache.fetch_message(self._channel_id, self._referenced_message_id)

    def get_referenced_message(self) -> Optional["Message"]:
        """
        Get the message this message is referencing, if any.

        Returns:
            The referenced message, if found

        """
        if self._referenced_message_id is None:
            return None
        return self._client.cache.get_message(self._channel_id, self._referenced_message_id)

    @classmethod
    def _process_dict(cls, data: dict, client: "Client") -> dict:
        if author_data := data.pop("author", None):
            if "guild_id" in data and "member" in data:
                author_data["member"] = data.pop("member")
                data["author_id"] = client.cache.place_member_data(data["guild_id"], author_data).id
            else:
                data["author_id"] = client.cache.place_user_data(author_data).id

        if mentions_data := data.pop("mentions", None):
            mention_ids = []
            for user_data in mentions_data:
                if "guild_id" in data and "member" in user_data:
                    mention_ids.append(client.cache.place_member_data(data["guild_id"], user_data).id)
                else:
                    mention_ids.append(client.cache.place_user_data(user_data).id)
            data["mention_ids"] = mention_ids

        found_ids = []
        mention_channels = []
        if "mention_channels" in data:
            for channel_data in data["mention_channels"]:
                mention_channels.append(ChannelMention.from_dict(channel_data, client))
                found_ids.append(channel_data["id"])
        if "content" in data:
            for channel_id in channel_mention.findall(data["content"]):
                if channel_id not in found_ids and (channel := client.get_channel(channel_id)):
                    channel_data = {
                        "id": channel.id,
                        "guild_id": channel._guild_id,
                        "type": channel.type,
                        "name": channel.name,
                    }
                    mention_channels.append(ChannelMention.from_dict(channel_data, client))
        if len(mention_channels) > 0:
            data["mention_channels"] = mention_channels

        if "attachments" in data:
            data["attachments"] = Attachment.from_list(data.get("attachments"), client)

        if "embeds" in data:
            data["embeds"] = models.Embed.from_list(data.get("embeds"))

        if "reactions" in data:
            reactions = []
            for reaction_data in data["reactions"]:
                reactions.append(
                    models.Reaction.from_dict(
                        reaction_data | {"message_id": data["id"], "channel_id": data["channel_id"]}, client
                    )
                )
            data["reactions"] = reactions

        # TODO: Convert to application object

        if ref_message_data := data.pop("referenced_message", None):
            if not ref_message_data.get("guild_id"):
                ref_message_data["guild_id"] = data.get("guild_id")
            _m = client.cache.place_message_data(ref_message_data)
            data["referenced_message_id"] = _m.id

        if "interaction" in data:
            data["interaction"] = MessageInteraction.from_dict(data["interaction"], client)

        if thread_data := data.pop("thread", None):
            data["thread_channel_id"] = client.cache.place_channel_data(thread_data).id

        if "components" in data:
            components = []
            for component_data in data["components"]:
                components.append(models.BaseComponent.from_dict_factory(component_data))
            data["components"] = components

        if "sticker_items" in data:
            data["sticker_items"] = models.StickerItem.from_list(data["sticker_items"], client)

        return data

    @property
    def system_content(self) -> Optional[str]:
        """Content for system messages. (boosts, welcomes, etc)"""
        match self.type:
            case MessageTypes.USER_PREMIUM_GUILD_SUBSCRIPTION:
                return f"{self.author.mention} just boosted the server!"
            case MessageTypes.USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_1:
                return f"{self.author.mention} just boosted the server! {self.guild.name} has achieved **Level 1!**"
            case MessageTypes.USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_2:
                return f"{self.author.mention} just boosted the server! {self.guild.name} has achieved **Level 2!**"
            case MessageTypes.USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_3:
                return f"{self.author.mention} just boosted the server! {self.guild.name} has achieved **Level 3!**"
            case MessageTypes.GUILD_MEMBER_JOIN:
                return GUILD_WELCOME_MESSAGES[
                    int(self.timestamp.timestamp() * 1000)
                    % len(GUILD_WELCOME_MESSAGES)
                    # This is how Discord calculates the welcome message.
                ].format(self.author.mention)
            case MessageTypes.THREAD_CREATED:
                return f"{self.author.mention} started a thread: {self.thread.mention}. See all **threads**."
            case MessageTypes.CHANNEL_FOLLOW_ADD:
                return f"{self.author.mention} has added **{self.content}** to this channel. Its most important updates will show up here."
            case MessageTypes.RECIPIENT_ADD:
                return f"{self.author.mention} added <@{self._mention_ids[0]}> to the thread."
            case MessageTypes.RECIPIENT_REMOVE:
                return f"{self.author.mention} removed <@{self._mention_ids[0]}> from the thread."
            case MessageTypes.CHANNEL_NAME_CHANGE:
                return f"{self.author.mention} changed the channel name: **{self.content}**."
            case MessageTypes.CHANNEL_PINNED_MESSAGE:
                return f"{self.author.mention} pinned a message. See all pinned messages"
            case MessageTypes.GUILD_DISCOVERY_DISQUALIFIED:
                return "This server has been removed from Server Discovery because it no longer passes all the requirements. Check Server Settings for more details."
            case MessageTypes.GUILD_DISCOVERY_REQUALIFIED:
                return "This server is eligible for Server Discovery again and has been automatically relisted!"
            case MessageTypes.GUILD_DISCOVERY_GRACE_PERIOD_INITIAL_WARNING:
                return "This server has failed Discovery activity requirements for 1 week. If this server fails for 4 weeks in a row, it will be automatically removed from Discovery."
            case MessageTypes.GUILD_DISCOVERY_GRACE_PERIOD_FINAL_WARNING:
                return "This server has failed Discovery activity requirements for 3 weeks in a row. If this server fails for 1 more week, it will be removed from Discovery."
            case MessageTypes.GUILD_INVITE_REMINDER:
                return "**Invite your friends**\nThe best way to setup a server is with your buddies!"
            case MessageTypes.THREAD_STARTER_MESSAGE:
                if referenced_message := self.get_referenced_message():
                    return referenced_message.content
                return "Sorry, we couldn't load the first message in this thread"
            case MessageTypes.AUTO_MODERATION_ACTION:
                keyword_matched_content = self.embeds[0].fields[4].value  # The words that triggered the action
                message_content = self.embeds[0].description.replace(
                    keyword_matched_content, f"**{keyword_matched_content}**"
                )
                rule = self.embeds[0].fields[0].value  # What rule was triggered
                channel = self.embeds[0].fields[1].value  # Channel that the action took place in
                return f'AutoMod has blocked a message in <#{channel}>. "{message_content}" from {self.author.mention}. Rule: {rule}.'
            case _:
                return None

    @property
    def jump_url(self) -> str:
        """A url that allows the client to *jump* to this message."""
        return f"https://discord.com/channels/{self._guild_id or '@me'}/{self._channel_id}/{self.id}"

    @property
    def proto_url(self) -> str:
        """A URL like `jump_url` that uses protocols."""
        return f"discord://-/channels/{self._guild_id or '@me'}/{self._channel_id}/{self.id}"

    async def edit(
        self,
        content: Optional[str] = None,
        embeds: Optional[Union[Sequence[Union["models.Embed", dict]], Union["models.Embed", dict]]] = None,
        embed: Optional[Union["models.Embed", dict]] = None,
        components: Optional[
            Union[
                Sequence[Sequence[Union["models.BaseComponent", dict]]],
                Sequence[Union["models.BaseComponent", dict]],
                "models.BaseComponent",
                dict,
            ]
        ] = None,
        allowed_mentions: Optional[Union[AllowedMentions, dict]] = None,
        attachments: Optional[Optional[Sequence[Union[Attachment, dict]]]] = None,
        files: Optional[Union[UPLOADABLE_TYPE, Sequence[UPLOADABLE_TYPE]]] = None,
        file: Optional[UPLOADABLE_TYPE] = None,
        tts: bool = False,
        flags: Optional[Union[int, MessageFlags]] = None,
    ) -> "Message":
        """
        Edits the message.

        Args:
            content: Message text content.
            embeds: Embedded rich content (up to 6000 characters).
            embed: Embedded rich content (up to 6000 characters).
            components: The components to include with the message.
            allowed_mentions: Allowed mentions for the message.
            attachments: The attachments to keep, only used when editing message.
            files: Files to send, the path, bytes or File() instance, defaults to None. You may have up to 10 files.
            file: Files to send, the path, bytes or File() instance, defaults to None. You may have up to 10 files.
            tts: Should this message use Text To Speech.
            flags: Message flags to apply.

        Returns:
            New message object with edits applied

        """
        message_payload = process_message_payload(
            content=content,
            embeds=embeds or embed,
            components=components,
            allowed_mentions=allowed_mentions,
            attachments=attachments,
            tts=tts,
            flags=flags,
        )

        if self.flags == MessageFlags.EPHEMERAL:
            raise EphemeralEditException

        message_data = await self._client.http.edit_message(message_payload, self._channel_id, self.id, files=files)
        if message_data:
            return self._client.cache.place_message_data(message_data)

    async def delete(self, delay: Absent[Optional[int]] = MISSING) -> None:
        """
        Delete message.

        Args:
            delay: Seconds to wait before deleting message.

        """
        if delay and delay > 0:

            async def delayed_delete() -> None:
                await asyncio.sleep(delay)
                try:
                    await self._client.http.delete_message(self._channel_id, self.id)
                except Exception:  # noqa: S110
                    pass  # No real way to handle this

            asyncio.create_task(delayed_delete())

        else:
            await self._client.http.delete_message(self._channel_id, self.id)

    async def reply(
        self,
        content: Optional[str] = None,
        embeds: Optional[Union[List[Union["models.Embed", dict]], Union["models.Embed", dict]]] = None,
        embed: Optional[Union["models.Embed", dict]] = None,
        **kwargs: Mapping[str, Any],
    ) -> "Message":
        """
        Reply to this message, takes all the same attributes as `send`.

        Args:
            content: Message text content.
            embeds: Embedded rich content (up to 6000 characters).
            embed: Embedded rich content (up to 6000 characters).
            **kwargs: Additional options to pass to `send`.

        Returns:
            New message object.

        """
        return await self.channel.send(content=content, reply_to=self, embeds=embeds or embed, **kwargs)

    async def create_thread(
        self,
        name: str,
        auto_archive_duration: Union[AutoArchiveDuration, int] = AutoArchiveDuration.ONE_DAY,
        reason: Optional[str] = None,
    ) -> "models.TYPE_THREAD_CHANNEL":
        """
        Create a thread from this message.

        Args:
            name: The name of this thread
            auto_archive_duration: duration in minutes to automatically archive the thread after recent activity, can be set to: 60, 1440, 4320, 10080
            reason: The optional reason for creating this thread

        Returns:
            The created thread object

        Raises:
            ThreadOutsideOfGuild: if this is invoked on a message outside of a guild

        """
        if self.channel.type not in (ChannelTypes.GUILD_TEXT, ChannelTypes.GUILD_NEWS):
            raise ThreadOutsideOfGuild

        thread_data = await self._client.http.create_thread(
            channel_id=self._channel_id,
            name=name,
            auto_archive_duration=auto_archive_duration,
            message_id=self.id,
            reason=reason,
        )
        return self._client.cache.place_channel_data(thread_data)

    async def suppress_embeds(self) -> "Message":
        """
        Suppress embeds for this message.

        !!! note
            Requires the `Permissions.MANAGE_MESSAGES` permission.

        """
        message_data = await self._client.http.edit_message(
            {"flags": MessageFlags.SUPPRESS_EMBEDS}, self._channel_id, self.id
        )
        if message_data:
            return self._client.cache.place_message_data(message_data)

    async def fetch_reaction(
        self,
        emoji: Union["models.PartialEmoji", dict, str],
        limit: Absent[int] = MISSING,
        after: Absent["Snowflake_Type"] = MISSING,
    ) -> List["models.User"]:
        """
        Fetches reactions of a specific emoji from this message.

        Args:
            emoji: The emoji to get
            limit: Max number of users to return (1-100)
            after: Get users after this user ID

        Returns:
            list of users who have reacted with that emoji

        """
        reaction_data = await self._client.http.get_reactions(
            self._channel_id, self.id, emoji, limit, to_optional_snowflake(after)
        )
        return [self._client.cache.place_user_data(user_data) for user_data in reaction_data]

    async def add_reaction(self, emoji: Union["models.PartialEmoji", dict, str]) -> None:
        """
        Add a reaction to this message.

        Args:
            emoji: the emoji to react with

        """
        emoji = models.process_emoji_req_format(emoji)
        await self._client.http.create_reaction(self._channel_id, self.id, emoji)

    async def remove_reaction(
        self,
        emoji: Union["models.PartialEmoji", dict, str],
        member: Optional[Union["models.Member", "models.User", "Snowflake_Type"]] = MISSING,
    ) -> None:
        """
        Remove a specific reaction that a user reacted with.

        Args:
            emoji: Emoji to remove
            member: Member to remove reaction of. Default's to NAFF bot user.

        """
        emoji_str = models.process_emoji_req_format(emoji)
        if not member:
            member = self._client.user
        user_id = to_snowflake(member)
        if user_id == self._client.user.id:
            await self._client.http.remove_self_reaction(self._channel_id, self.id, emoji_str)
        else:
            await self._client.http.remove_user_reaction(self._channel_id, self.id, emoji_str, user_id)

    async def clear_reactions(self, emoji: Union["models.PartialEmoji", dict, str]) -> None:
        """
        Clear a specific reaction from message.

        Args:
            emoji: The emoji to clear

        """
        emoji = models.process_emoji_req_format(emoji)
        await self._client.http.clear_reaction(self._channel_id, self.id, emoji)

    async def clear_all_reactions(self) -> None:
        """Clear all emojis from a message."""
        await self._client.http.clear_reactions(self._channel_id, self.id)

    async def pin(self) -> None:
        """Pin message."""
        await self._client.http.pin_message(self._channel_id, self.id)
        self.pinned = True

    async def unpin(self) -> None:
        """Unpin message."""
        await self._client.http.unpin_message(self._channel_id, self.id)
        self.pinned = False

    async def publish(self) -> None:
        """
        Publish this message.

        (Discord api calls it "crosspost")

        """
        await self._client.http.crosspost_message(self._channel_id, self.id)


def process_allowed_mentions(allowed_mentions: Optional[Union[AllowedMentions, dict]]) -> Optional[dict]:
    """
    Process allowed mentions into a dictionary.

    Args:
        allowed_mentions: Allowed mentions object or dictionary

    Returns:
        Dictionary of allowed mentions

    Raises:
        ValueError: Invalid allowed mentions

    """
    if not allowed_mentions:
        return allowed_mentions

    if isinstance(allowed_mentions, dict):
        return allowed_mentions

    if isinstance(allowed_mentions, AllowedMentions):
        return allowed_mentions.to_dict()

    raise ValueError(f"Invalid allowed mentions: {allowed_mentions}")


def process_message_reference(
    message_reference: Optional[Union[MessageReference, Message, dict, "Snowflake_Type"]]
) -> Optional[dict]:
    """
    Process mention references into a dictionary.

    Args:
        message_reference: Message reference object

    Returns:
        Message reference dictionary

    Raises:
        ValueError: Invalid message reference

    """
    if not message_reference:
        return message_reference

    if isinstance(message_reference, dict):
        return message_reference

    if isinstance(message_reference, (str, int)):
        message_reference = MessageReference(message_id=message_reference)

    if isinstance(message_reference, Message):
        message_reference = MessageReference.for_message(message_reference)

    if isinstance(message_reference, MessageReference):
        return message_reference.to_dict()

    raise ValueError(f"Invalid message reference: {message_reference}")


def process_message_payload(
    content: Optional[str] = None,
    embeds: Optional[Union[List[Union["models.Embed", dict]], Union["models.Embed", dict]]] = None,
    components: Optional[
        Union[
            List[List[Union["models.BaseComponent", dict]]],
            List[Union["models.BaseComponent", dict]],
            "models.BaseComponent",
            dict,
        ]
    ] = None,
    stickers: Optional[
        Union[List[Union["models.Sticker", "Snowflake_Type"]], "models.Sticker", "Snowflake_Type"]
    ] = None,
    allowed_mentions: Optional[Union[AllowedMentions, dict]] = None,
    reply_to: Optional[Union[MessageReference, Message, dict, "Snowflake_Type"]] = None,
    attachments: Optional[List[Union[Attachment, dict]]] = None,
    tts: bool = False,
    flags: Optional[Union[int, MessageFlags]] = None,
    **kwargs,
) -> dict:
    """
    Format message content for it to be ready to send discord.

    Args:
        content: Message text content.
        embeds: Embedded rich content (up to 6000 characters).
        components: The components to include with the message.
        stickers: IDs of up to 3 stickers in the server to send in the message.
        allowed_mentions: Allowed mentions for the message.
        reply_to: Message to reference, must be from the same channel.
        attachments: The attachments to keep, only used when editing message.
        tts: Should this message use Text To Speech.
        flags: Message flags to apply.

    Returns:
        Dictionary

    """
    embeds = models.process_embeds(embeds)
    if isinstance(embeds, list):
        embeds = embeds if all(e is not None for e in embeds) else None

    components = models.process_components(components)
    if stickers:
        stickers = [to_snowflake(sticker) for sticker in stickers]
    allowed_mentions = process_allowed_mentions(allowed_mentions)
    message_reference = process_message_reference(reply_to)
    if attachments:
        attachments = [attachment.to_dict() for attachment in attachments]

    return dict_filter_none(
        {
            "content": content,
            "embeds": embeds,
            "components": components,
            "sticker_ids": stickers,
            "allowed_mentions": allowed_mentions,
            "message_reference": message_reference,
            "attachments": attachments,
            "tts": tts,
            "flags": flags,
            **kwargs,
        }
    )
