from typing import Any, Optional, TYPE_CHECKING

import attrs

from naff.client.const import logger, MISSING, Absent
from naff.client.mixins.serialization import DictSerializationMixin
from naff.client.utils import list_converter, optional
from naff.client.utils.attr_utils import define, field, docs
from naff.models.discord.base import ClientObject, DiscordObject
from naff.models.discord.enums import AutoModTriggerType, AutoModAction, AutoModEvent, AutoModLanuguageType
from naff.models.discord.snowflake import to_snowflake_list, to_snowflake

if TYPE_CHECKING:
    from naff import (
        Snowflake_Type,
        Guild,
        GuildText,
        Message,
        Client,
        Member,
    )

__all__ = ("AutoModerationAction", "AutoModRule")


@define()
class BaseAction(DictSerializationMixin):
    """A base implementation of a moderation action

    Attributes:
        type: The type of action that was taken
    """

    type: AutoModAction = field(converter=AutoModAction)

    @classmethod
    def from_dict_factory(cls, data: dict) -> "BaseAction":
        action_class = ACTION_MAPPING.get(data.get("type"))
        if not action_class:
            logger.error(f"Unknown action type for {data}")
            action_class = cls

        return action_class.from_dict({"type": data.get("type")} | data["metadata"])

    def as_dict(self) -> dict:
        data = attrs.asdict(self)
        data["metadata"] = {k: data.pop(k) for k, v in data.copy().items() if k != "type"}
        return data


@define()
class BaseTrigger(DictSerializationMixin):
    """A base implementation of an auto-mod trigger

    Attributes:
        type: The type of event this trigger is for
    """

    type: AutoModTriggerType = field(converter=AutoModTriggerType, repr=True, metadata=docs("The type of trigger"))

    @classmethod
    def _process_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        data = super()._process_dict(data)

        if meta := data.get("trigger_metadata"):
            for key, val in meta.items():
                data[key] = val

        return data

    @classmethod
    def from_dict_factory(cls, data: dict) -> "BaseAction":
        trigger_class = TRIGGER_MAPPING.get(data.get("trigger_type"))
        meta = data.get("trigger_metadata", {})
        if not trigger_class:
            logger.error(f"Unknown trigger type for {data}")
            trigger_class = cls

        payload = {"type": data.get("trigger_type"), "trigger_metadata": meta}

        return trigger_class.from_dict(payload)

    def as_dict(self) -> dict:
        data = attrs.asdict(self)
        data["trigger_metadata"] = {k: data.pop(k) for k, v in data.copy().items() if k != "type"}
        data["trigger_type"] = data.pop("type")
        return data


def _keyword_converter(filter: str | list[str]) -> list[str]:
    if isinstance(filter, list):
        return filter
    return [filter]


@define()
class KeywordTrigger(BaseTrigger):
    """A trigger that checks if content contains words from a user defined list of keywords"""

    type: AutoModTriggerType = field(
        default=AutoModTriggerType.KEYWORD,
        converter=AutoModTriggerType,
        repr=True,
        metadata=docs("The type of trigger"),
    )
    keyword_filter: str | list[str] = field(
        factory=list, repr=True, metadata=docs("What words will trigger this"), converter=_keyword_converter
    )


@define()
class HarmfulLinkFilter(BaseTrigger):
    """A trigger that checks if content contains any harmful links"""

    type: AutoModTriggerType = field(
        default=AutoModTriggerType.HARMFUL_LINK,
        converter=AutoModTriggerType,
        repr=True,
        metadata=docs("The type of trigger"),
    )
    ...


@define()
class KeywordPresetTrigger(BaseTrigger):
    """A trigger that checks if content contains words from internal pre-defined wordsets"""

    type: AutoModTriggerType = field(
        default=AutoModTriggerType.KEYWORD_PRESET,
        converter=AutoModTriggerType,
        repr=True,
        metadata=docs("The type of trigger"),
    )
    keyword_lists: list[AutoModLanuguageType] = field(
        factory=list,
        converter=list_converter(AutoModLanuguageType),
        repr=True,
        metadata=docs("The preset list of keywords that will trigger this"),
    )


@define()
class MentionSpamTrigger(BaseTrigger):
    """A trigger that checks if content contains more mentions than allowed"""

    mention_total_limit: int = field(default=3, repr=True, metadata=docs("The maximum number of mentions allowed"))


@define()
class BlockMessage(BaseAction):
    """blocks the content of a message according to the rule"""

    type: AutoModAction = field(default=AutoModAction.BLOCK_MESSAGE, converter=AutoModAction)
    ...


@define()
class AlertMessage(BaseAction):
    """logs user content to a specified channel"""

    channel_id: "Snowflake_Type" = field(repr=True)
    type: AutoModAction = field(default=AutoModAction.ALERT_MESSAGE, converter=AutoModAction)


@define(kw_only=False)
class TimeoutUser(BaseAction):
    """timeout user for a specified duration"""

    duration_seconds: int = field(repr=True, default=60)
    type: AutoModAction = field(default=AutoModAction.TIMEOUT_USER, converter=AutoModAction)


@define()
class AutoModRule(DiscordObject):
    """A representation of an auto mod rule"""

    name: str = field()
    """The name of the rule"""
    enabled: bool = field(default=False)
    """whether the rule is enabled"""

    actions: list[BaseAction] = field(factory=list)
    """the actions which will execute when the rule is triggered"""
    event_type: AutoModEvent = field()
    """the rule event type"""
    trigger: BaseTrigger = field()
    """The trigger for this rule"""
    exempt_roles: list["Snowflake_Type"] = field(factory=list, converter=to_snowflake_list)
    """the role ids that should not be affected by the rule (Maximum of 20)"""
    exempt_channels: list["Snowflake_Type"] = field(factory=list, converter=to_snowflake_list)
    """the channel ids that should not be affected by the rule (Maximum of 50)"""

    _guild_id: "Snowflake_Type" = field(default=MISSING)
    """the guild which this rule belongs to"""
    _creator_id: "Snowflake_Type" = field(default=MISSING)
    """the user which first created this rule"""
    id: "Snowflake_Type" = field(default=MISSING, converter=optional(to_snowflake))

    @classmethod
    def _process_dict(cls, data: dict, client: "Client") -> dict:
        data = super()._process_dict(data, client)
        data["actions"] = [BaseAction.from_dict_factory(d) for d in data["actions"]]
        data["trigger"] = BaseTrigger.from_dict_factory(data)
        return data

    def to_dict(self) -> dict:
        data = super().to_dict()
        trigger = data.pop("trigger")
        data["trigger_type"] = trigger["trigger_type"]
        data["trigger_metadata"] = trigger["trigger_metadata"]
        return data

    @property
    def creator(self) -> "Member":
        """The original creator of this rule"""
        return self._client.cache.get_member(self._guild_id, self._creator_id)

    @property
    def guild(self) -> "Guild":
        """The guild this rule belongs to"""
        return self._client.cache.get_guild(self._guild_id)

    async def delete(self, reason: Absent[str] = MISSING) -> None:
        """
        Delete this rule

        Args:
            reason: The reason for deleting this rule
        """
        await self._client.http.delete_auto_moderation_rule(self._guild_id, self.id, reason=reason)

    async def modify(
        self,
        *,
        name: Absent[str] = MISSING,
        trigger: Absent[BaseTrigger] = MISSING,
        trigger_type: Absent[AutoModTriggerType] = MISSING,
        trigger_metadata: Absent[dict] = MISSING,
        actions: Absent[list[BaseAction]] = MISSING,
        exempt_channels: Absent[list["Snowflake_Type"]] = MISSING,
        exempt_roles: Absent[list["Snowflake_Type"]] = MISSING,
        event_type: Absent[AutoModEvent] = MISSING,
        enabled: Absent[bool] = MISSING,
        reason: Absent[str] = MISSING,
    ) -> "AutoModRule":
        """
        Modify an existing automod rule.

        Args:
            name: The name of the rule
            trigger: A trigger for this rule
            trigger_type: The type trigger for this rule (ignored if trigger specified)
            trigger_metadata: Metadata for the trigger (ignored if trigger specified)
            actions: A list of actions to take upon triggering
            exempt_roles: Roles that ignore this rule
            exempt_channels: Channels that ignore this role
            enabled: Is this rule enabled?
            event_type: The type of event that triggers this rule
            reason: The reason for this change

        Returns:
            The updated rule
        """
        if trigger:
            _data = trigger.to_dict()
            trigger_type = _data["trigger_type"]
            trigger_metadata = _data.get("trigger_metadata", {})

        out = await self._client.http.modify_auto_moderation_rule(
            self._guild_id,
            self.id,
            name=name,
            trigger_type=trigger_type,
            trigger_metadata=trigger_metadata,
            actions=actions,
            exempt_roles=to_snowflake_list(exempt_roles) if exempt_roles is not MISSING else MISSING,
            exempt_channels=to_snowflake_list(exempt_channels) if exempt_channels is not MISSING else MISSING,
            event_type=event_type,
            enabled=enabled,
            reason=reason,
        )
        return AutoModRule.from_dict(out, self._client)


@define()
class AutoModerationAction(ClientObject):
    rule_trigger_type: AutoModTriggerType = field(converter=AutoModTriggerType)
    rule_id: "Snowflake_Type" = field()

    action: BaseAction = field(default=MISSING, repr=True)

    matched_keyword: str = field(repr=True)
    matched_content: Optional[str] = field(default=None)
    content: Optional[str] = field(default=None)

    _message_id: Optional["Snowflake_Type"] = field(default=None)
    _alert_system_message_id: Optional["Snowflake_Type"] = field(default=None)
    _channel_id: Optional["Snowflake_Type"] = field(default=None)
    _guild_id: "Snowflake_Type" = field()

    @classmethod
    def _process_dict(cls, data: dict, client: "Client") -> dict:
        data = super()._process_dict(data, client)
        data["action"] = BaseAction.from_dict_factory(data["action"])
        return data

    @property
    def guild(self) -> "Guild":
        return self._client.get_guild(self._guild_id)

    @property
    def channel(self) -> "Optional[GuildText]":
        return self._client.get_channel(self._channel_id)

    @property
    def message(self) -> "Optional[Message]":
        return self._client.cache.get_message(self._channel_id, self._message_id)


ACTION_MAPPING = {
    AutoModAction.BLOCK_MESSAGE: BlockMessage,
    AutoModAction.ALERT_MESSAGE: AlertMessage,
    AutoModAction.TIMEOUT_USER: TimeoutUser,
}

TRIGGER_MAPPING = {
    AutoModTriggerType.KEYWORD: KeywordTrigger,
    AutoModTriggerType.HARMFUL_LINK: HarmfulLinkFilter,
    AutoModTriggerType.KEYWORD_PRESET: KeywordPresetTrigger,
    AutoModTriggerType.MENTION_SPAM: MentionSpamTrigger,
}
