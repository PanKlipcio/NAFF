import asyncio
import inspect
import re
import typing
from enum import IntEnum
from typing import TYPE_CHECKING, Annotated, Callable, Coroutine, Dict, List, Union, Optional, Any

import attrs
from attr import Attribute

import naff.models.discord.channel as channel
from naff.client.const import (
    GLOBAL_SCOPE,
    SLASH_CMD_NAME_LENGTH,
    SLASH_CMD_MAX_OPTIONS,
    SLASH_CMD_MAX_DESC_LENGTH,
    MISSING,
    logger,
    Absent,
)
from naff.client.mixins.serialization import DictSerializationMixin
from naff.client.utils import optional
from naff.client.utils.attr_utils import define, field, docs, attrs_validator
from naff.client.utils.misc_utils import get_parameters
from naff.client.utils.serializer import no_export_meta
from naff.models.discord.enums import ChannelTypes, CommandTypes, Permissions
from naff.models.discord.role import Role
from naff.models.discord.snowflake import to_snowflake_list, to_snowflake
from naff.models.discord.user import BaseUser
from naff.models.naff.auto_defer import AutoDefer
from naff.models.naff.command import BaseCommand
from naff.models.naff.localisation import LocalisedField

if TYPE_CHECKING:
    from naff.models.discord.snowflake import Snowflake_Type
    from naff.models.naff.context import Context

__all__ = (
    "OptionTypes",
    "CallbackTypes",
    "InteractionCommand",
    "ContextMenu",
    "SlashCommandChoice",
    "SlashCommandOption",
    "SlashCommand",
    "ComponentCommand",
    "ModalCommand",
    "slash_command",
    "subcommand",
    "context_menu",
    "component_callback",
    "slash_option",
    "slash_default_member_permission",
    "auto_defer",
    "application_commands_to_dict",
    "sync_needed",
    "LocalisedName",
    "LocalizedName",
    "LocalizedDesc",
    "LocalisedDesc",
)


def name_validator(_: Any, attr: Attribute, value: str) -> None:
    if value:
        if not re.match(rf"^[\w-]{{1,{SLASH_CMD_NAME_LENGTH}}}$", value) or value != value.lower():
            raise ValueError(
                f"Slash Command names must be lower case and match this regex: ^[\w-]{1, {SLASH_CMD_NAME_LENGTH} }$"  # noqa: W605
            )


def desc_validator(_: Any, attr: Attribute, value: str) -> None:
    if value:
        if not 1 <= len(value) <= SLASH_CMD_MAX_DESC_LENGTH:
            raise ValueError(f"Description must be between 1 and {SLASH_CMD_MAX_DESC_LENGTH} characters long")


@define(field_transformer=attrs_validator(name_validator, skip_fields=["default_locale"]))
class LocalisedName(LocalisedField):
    """A localisation object for names."""

    def __repr__(self) -> str:
        return super().__repr__()


@define(field_transformer=attrs_validator(desc_validator, skip_fields=["default_locale"]))
class LocalisedDesc(LocalisedField):
    """A localisation object for descriptions."""

    def __repr__(self) -> str:
        return super().__repr__()


LocalizedName = LocalisedName
LocalizedDesc = LocalisedDesc


class OptionTypes(IntEnum):
    """Option types supported by slash commands."""

    SUB_COMMAND = 1
    SUB_COMMAND_GROUP = 2
    STRING = 3
    INTEGER = 4
    BOOLEAN = 5
    USER = 6
    CHANNEL = 7
    ROLE = 8
    MENTIONABLE = 9
    NUMBER = 10
    ATTACHMENT = 11

    @classmethod
    def from_type(cls, t: type) -> "OptionTypes":
        """
        Convert data types to their corresponding OptionType.

        Args:
            t: The datatype to convert

        Returns:
            OptionType or None

        """
        if issubclass(t, str):
            return cls.STRING
        if issubclass(t, int):
            return cls.INTEGER
        if issubclass(t, bool):
            return cls.BOOLEAN
        if issubclass(t, BaseUser):
            return cls.USER
        if issubclass(t, channel.BaseChannel):
            return cls.CHANNEL
        if issubclass(t, Role):
            return cls.ROLE
        if issubclass(t, float):
            return cls.NUMBER


class CallbackTypes(IntEnum):
    """Types of callback supported by interaction response."""

    PONG = 1
    CHANNEL_MESSAGE_WITH_SOURCE = 4
    DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE = 5
    DEFERRED_UPDATE_MESSAGE = 6
    UPDATE_MESSAGE = 7
    AUTOCOMPLETE_RESULT = 8
    MODAL = 9


@define()
class InteractionCommand(BaseCommand):
    """
    Represents a discord abstract interaction command.

    Attributes:
        scope: Denotes whether its global or for specific guild.
        default_member_permissions: What permissions members need to have by default to use this command.
        dm_permission: Should this command be available in DMs.
        cmd_id: The id of this command given by discord.
        callback: The coroutine to callback when this interaction is received.

    """

    name: LocalisedName = field(
        metadata=docs("1-32 character name") | no_export_meta, converter=LocalisedName.converter
    )
    scopes: List["Snowflake_Type"] = field(
        default=[GLOBAL_SCOPE],
        converter=to_snowflake_list,
        metadata=docs("The scopes of this interaction. Global or guild ids") | no_export_meta,
    )
    default_member_permissions: Optional["Permissions"] = field(
        default=None, metadata=docs("What permissions members need to have by default to use this command")
    )
    dm_permission: bool = field(default=True, metadata=docs("Whether this command is enabled in DMs"))
    cmd_id: Dict[str, "Snowflake_Type"] = field(
        factory=dict, metadata=docs("The unique IDs of this commands") | no_export_meta
    )  # scope: cmd_id
    callback: Callable[..., Coroutine] = field(
        default=None, metadata=docs("The coroutine to call when this interaction is received") | no_export_meta
    )
    auto_defer: "AutoDefer" = field(
        default=MISSING,
        metadata=docs("A system to automatically defer this command after a set duration") | no_export_meta,
    )
    nsfw: bool = field(default=False, metadata=docs("This command should only work in NSFW channels"))
    _application_id: "Snowflake_Type" = field(default=None, converter=optional(to_snowflake))

    def __attrs_post_init__(self) -> None:
        if self.callback is not None:
            if hasattr(self.callback, "auto_defer"):
                self.auto_defer = self.callback.auto_defer

        super().__attrs_post_init__()

    def to_dict(self) -> dict:
        data = super().to_dict()

        if self.default_member_permissions is not None:
            data["default_member_permissions"] = str(int(self.default_member_permissions))
        else:
            data["default_member_permissions"] = None

        return data

    def mention(self, scope: Optional["Snowflake_Type"] = None) -> str:
        """
        Returns a string that would mention the interaction.

        Args:
            scope: If the command is available in multiple scope, specify which scope to get the mention for. Defaults to the first available one if not specified.

        Returns:
            The markdown mention.
        """
        if scope:
            cmd_id = self.get_cmd_id(scope=scope)
        else:
            cmd_id = list(self.cmd_id.values())[0]

        return f"</{self.resolved_name}:{cmd_id}>"

    @property
    def resolved_name(self) -> str:
        """A representation of this interaction's name."""
        return str(self.name)

    def get_localised_name(self, locale: str) -> str:
        return self.name.get_locale(locale)

    def get_cmd_id(self, scope: "Snowflake_Type") -> "Snowflake_Type":
        return self.cmd_id.get(scope, self.cmd_id.get(GLOBAL_SCOPE, None))

    @property
    def is_subcommand(self) -> bool:
        return False

    async def _permission_enforcer(self, ctx: "Context") -> bool:
        """A check that enforces Discord permissions."""
        # I wish this wasn't needed, but unfortunately Discord permissions cant be trusted to actually prevent usage
        if self.dm_permission is False:
            return ctx.guild is not None
        return True


@define()
class ContextMenu(InteractionCommand):
    """
    Represents a discord context menu.

    Attributes:
        name: The name of this entry.
        type: The type of entry (user or message).

    """

    name: LocalisedField = field(metadata=docs("1-32 character name"), converter=LocalisedField.converter)
    type: CommandTypes = field(metadata=docs("The type of command, defaults to 1 if not specified"))

    @type.validator
    def _type_validator(self, attribute: str, value: int) -> None:
        if not isinstance(value, CommandTypes):
            if value not in CommandTypes.__members__.values():
                raise ValueError("Context Menu type not recognised, please consult the docs.")
        elif value == CommandTypes.CHAT_INPUT:
            raise ValueError(
                "The CHAT_INPUT type is basically slash commands. Please use the @slash_command() " "decorator instead."
            )

    def to_dict(self) -> dict:
        data = super().to_dict()

        data["name"] = str(self.name)
        return data


@define(kw_only=False)
class SlashCommandChoice(DictSerializationMixin):
    """
    Represents a discord slash command choice.

    Attributes:
        name: The name the user will see
        value: The data sent to your code when this choice is used

    """

    name: LocalisedField = field(converter=LocalisedField.converter)
    value: Union[str, int, float] = field()

    def as_dict(self) -> dict:
        return {"name": str(self.name), "value": self.value, "name_localizations": self.name.to_locale_dict()}


@define(kw_only=False)
class SlashCommandOption(DictSerializationMixin):
    """
    Represents a discord slash command option.

    Attributes:
        name: The name of this option
        type: The type of option
        description: The description of this option
        required: "This option must be filled to use the command"
        choices: A list of choices the user has to pick between
        channel_types: The channel types permitted. The option needs to be a channel
        min_value: The minimum value permitted. The option needs to be an integer or float
        max_value: The maximum value permitted. The option needs to be an integer or float
        min_length: The minimum length of text a user can input. The option needs to be a string
        max_length: The maximum length of text a user can input. The option needs to be a string

    """

    name: LocalisedName = field(converter=LocalisedName.converter)
    type: Union[OptionTypes, int] = field()
    description: LocalisedDesc = field(default="No Description Set", converter=LocalisedDesc.converter)
    required: bool = field(default=True)
    autocomplete: bool = field(default=False)
    choices: List[Union[SlashCommandChoice, Dict]] = field(factory=list)
    channel_types: Optional[list[Union[ChannelTypes, int]]] = field(default=None)
    min_value: Optional[float] = field(default=None)
    max_value: Optional[float] = field(default=None)
    min_length: Optional[int] = field(default=None)
    max_length: Optional[int] = field(default=None)

    @type.validator
    def _type_validator(self, attribute: str, value: int) -> None:
        if value == OptionTypes.SUB_COMMAND or value == OptionTypes.SUB_COMMAND_GROUP:
            raise ValueError(
                "Options cannot be SUB_COMMAND or SUB_COMMAND_GROUP. If you want to use subcommands, "
                "see the @sub_command() decorator."
            )

    @channel_types.validator
    def _channel_types_validator(self, attribute: str, value: Optional[list[OptionTypes]]) -> None:
        if value is not None:
            if self.type != OptionTypes.CHANNEL:
                raise ValueError("The option needs to be CHANNEL to use this")

            allowed_int = [channel_type.value for channel_type in ChannelTypes]
            for item in value:
                if (item not in allowed_int) and (item not in ChannelTypes):
                    raise ValueError(f"{value} is not allowed here")

    @min_value.validator
    def _min_value_validator(self, attribute: str, value: Optional[float]) -> None:
        if value is not None:
            if self.type != OptionTypes.INTEGER and self.type != OptionTypes.NUMBER:
                raise ValueError("`min_value` can only be supplied with int or float options")

            if self.type == OptionTypes.INTEGER:
                if isinstance(value, float):
                    raise ValueError("`min_value` needs to be an int in an int option")

            if self.max_value is not None and self.min_value is not None:
                if self.max_value < self.min_value:
                    raise ValueError("`min_value` needs to be <= than `max_value`")

    @max_value.validator
    def _max_value_validator(self, attribute: str, value: Optional[float]) -> None:
        if value is not None:
            if self.type != OptionTypes.INTEGER and self.type != OptionTypes.NUMBER:
                raise ValueError("`max_value` can only be supplied with int or float options")

            if self.type == OptionTypes.INTEGER:
                if isinstance(value, float):
                    raise ValueError("`max_value` needs to be an int in an int option")

            if self.max_value and self.min_value:
                if self.max_value < self.min_value:
                    raise ValueError("`min_value` needs to be <= than `max_value`")

    @min_length.validator
    def _min_length_validator(self, attribute: str, value: Optional[int]) -> None:
        if value is not None:
            if self.type != OptionTypes.STRING:
                raise ValueError("`min_length` can only be supplied with string options")

            if self.max_length is not None and self.min_length is not None:
                if self.max_length < self.min_length:
                    raise ValueError("`min_length` needs to be <= than `max_length`")

            if self.min_length < 0:
                raise ValueError("`min_length` needs to be >= 0")

    @max_length.validator
    def _max_length_validator(self, attribute: str, value: Optional[int]) -> None:
        if value is not None:
            if self.type != OptionTypes.STRING:
                raise ValueError("`max_length` can only be supplied with string options")

            if self.min_length is not None and self.max_length is not None:
                if self.max_length < self.min_length:
                    raise ValueError("`min_length` needs to be <= than `max_length`")

            if self.max_length < 1:
                raise ValueError("`max_length` needs to be >= 1")

    def as_dict(self) -> dict:
        data = attrs.asdict(self)
        data["name"] = str(self.name)
        data["description"] = str(self.description)
        data["choices"] = [
            choice.as_dict() if isinstance(choice, SlashCommandChoice) else choice for choice in self.choices
        ]
        data["name_localizations"] = self.name.to_locale_dict()
        data["description_localizations"] = self.description.to_locale_dict()

        return data


@define()
class SlashCommand(InteractionCommand):
    name: LocalisedName = field(converter=LocalisedName.converter)
    description: LocalisedDesc = field(default="No Description Set", converter=LocalisedDesc.converter)

    group_name: LocalisedName = field(default=None, metadata=no_export_meta, converter=LocalisedName.converter)
    group_description: LocalisedDesc = field(
        default="No Description Set", metadata=no_export_meta, converter=LocalisedDesc.converter
    )

    sub_cmd_name: LocalisedName = field(default=None, metadata=no_export_meta, converter=LocalisedName.converter)
    sub_cmd_description: LocalisedDesc = field(
        default="No Description Set", metadata=no_export_meta, converter=LocalisedDesc.converter
    )

    options: List[Union[SlashCommandOption, Dict]] = field(factory=list)
    autocomplete_callbacks: dict = field(factory=dict, metadata=no_export_meta)

    @property
    def resolved_name(self) -> str:
        return (
            f"{self.name}"
            f"{f' {self.group_name}' if bool(self.group_name) else ''}"
            f"{f' {self.sub_cmd_name}' if bool(self.sub_cmd_name) else ''}"
        )

    def get_localised_name(self, locale: str) -> str:
        return (
            f"{self.name.get_locale(locale)}"
            f"{f' {self.group_name.get_locale(locale)}' if bool(self.group_name) else ''}"
            f"{f' {self.sub_cmd_name.get_locale(locale)}' if bool(self.sub_cmd_name) else ''}"
        )

    @property
    def is_subcommand(self) -> bool:
        return bool(self.sub_cmd_name)

    def __attrs_post_init__(self) -> None:
        if self.callback is not None:
            params = get_parameters(self.callback)
            for name, val in params.items():
                annotation = None
                if val.annotation and isinstance(val.annotation, SlashCommandOption):
                    annotation = val.annotation
                elif typing.get_origin(val.annotation) is Annotated:
                    for ann in typing.get_args(val.annotation):
                        if isinstance(ann, SlashCommandOption):
                            annotation = ann

                if annotation:
                    if not self.options:
                        self.options = []
                    annotation.name = name
                    self.options.append(annotation)

            if hasattr(self.callback, "options"):
                if not self.options:
                    self.options = []
                self.options += self.callback.options

        super().__attrs_post_init__()

    def to_dict(self) -> dict:
        data = super().to_dict()

        if self.is_subcommand:
            data["name"] = str(self.sub_cmd_name)
            data["description"] = str(self.sub_cmd_description)
            data["name_localizations"] = self.sub_cmd_name.to_locale_dict()
            data["description_localizations"] = self.sub_cmd_description.to_locale_dict()
            data.pop("default_member_permissions", None)
            data.pop("dm_permission", None)
            data.pop("nsfw", None)
        else:
            data["name_localizations"] = self.name.to_locale_dict()
            data["description_localizations"] = self.description.to_locale_dict()
        return data

    @options.validator
    def options_validator(self, attribute: str, value: List) -> None:
        if value:
            if isinstance(value, list):
                if len(value) > SLASH_CMD_MAX_OPTIONS:
                    raise ValueError(f"Slash commands can only hold {SLASH_CMD_MAX_OPTIONS} options")
                if value != sorted(
                    value,
                    key=lambda x: x.required if isinstance(x, SlashCommandOption) else x["required"],
                    reverse=True,
                ):
                    raise ValueError("Required options must go before optional options")

            else:
                raise TypeError("Options attribute must be either None or a list of options")

    def autocomplete(self, option_name: str) -> Callable[..., Coroutine]:
        """A decorator to declare a coroutine as an option autocomplete."""

        def wrapper(call: Callable[..., Coroutine]) -> Callable[..., Coroutine]:
            if not asyncio.iscoroutinefunction(call):
                raise TypeError("autocomplete must be coroutine")
            self.autocomplete_callbacks[option_name] = call

            # automatically set the option's autocomplete attribute to True
            for opt in self.options:
                if isinstance(opt, dict) and str(opt["name"]) == option_name:
                    opt["autocomplete"] = True
                elif isinstance(opt, SlashCommandOption) and str(opt.name) == option_name:
                    opt.autocomplete = True

            return call

        option_name = option_name.lower()
        return wrapper

    def group(self, name: str = None, description: str = "No Description Set") -> "SlashCommand":

        return SlashCommand(
            name=self.name,
            description=self.description,
            group_name=name,
            group_description=description,
            scopes=self.scopes,
        )

    def subcommand(
        self,
        sub_cmd_name: LocalisedName | str,
        group_name: LocalisedName | str = None,
        sub_cmd_description: Absent[LocalisedDesc | str] = MISSING,
        group_description: Absent[LocalisedDesc | str] = MISSING,
        options: List[Union[SlashCommandOption, Dict]] = None,
        nsfw: bool = False,
    ) -> Callable[..., "SlashCommand"]:
        def wrapper(call: Callable[..., Coroutine]) -> "SlashCommand":
            nonlocal sub_cmd_description

            if not asyncio.iscoroutinefunction(call):
                raise TypeError("Subcommand must be coroutine")

            if sub_cmd_description is MISSING:
                sub_cmd_description = call.__doc__ or "No Description Set"

            return SlashCommand(
                name=self.name,
                description=self.description,
                group_name=group_name or self.group_name,
                group_description=group_description or self.group_description,
                sub_cmd_name=sub_cmd_name,
                sub_cmd_description=sub_cmd_description,
                default_member_permissions=self.default_member_permissions,
                dm_permission=self.dm_permission,
                options=options,
                callback=call,
                scopes=self.scopes,
                nsfw=nsfw,
            )

        return wrapper


@define()
class ComponentCommand(InteractionCommand):
    # right now this adds no extra functionality, but for future dev ive implemented it
    name: str = field()
    listeners: list[str] = field(factory=list)


@define()
class ModalCommand(ComponentCommand):
    ...


def _unpack_helper(iterable: typing.Iterable[str]) -> list[str]:
    """
    Unpacks all types of iterable into a list of strings. Primarily to flatten generators.

    Args:
        iterable: The iterable of strings to unpack

    Returns:
        A list of strings
    """
    unpack = []
    for c in iterable:
        if inspect.isgenerator(c):
            unpack += list(c)
        else:
            unpack.append(c)
    return unpack


##############
# Decorators #
##############


def slash_command(
    name: str | LocalisedName,
    *,
    description: Absent[str | LocalisedDesc] = MISSING,
    scopes: Absent[List["Snowflake_Type"]] = MISSING,
    options: Optional[List[Union[SlashCommandOption, Dict]]] = None,
    default_member_permissions: Optional["Permissions"] = None,
    dm_permission: bool = True,
    sub_cmd_name: str | LocalisedName = None,
    group_name: str | LocalisedName = None,
    sub_cmd_description: str | LocalisedDesc = "No Description Set",
    group_description: str | LocalisedDesc = "No Description Set",
    nsfw: bool = False,
) -> Callable[[Callable[..., Coroutine]], SlashCommand]:
    """
    A decorator to declare a coroutine as a slash command.

    !!! note
        While the base and group descriptions arent visible in the discord client, currently.
        We strongly advise defining them anyway, if you're using subcommands, as Discord has said they will be visible in
        one of the future ui updates.

    Args:
        name: 1-32 character name of the command
        description: 1-100 character description of the command
        scopes: The scope this command exists within
        options: The parameters for the command, max 25
        default_member_permissions: What permissions members need to have by default to use this command.
        dm_permission: Should this command be available in DMs.
        sub_cmd_name: 1-32 character name of the subcommand
        sub_cmd_description: 1-100 character description of the subcommand
        group_name: 1-32 character name of the group
        group_description: 1-100 character description of the group
        nsfw: This command should only work in NSFW channels

    Returns:
        SlashCommand Object

    """

    def wrapper(func: Callable[..., Coroutine]) -> SlashCommand:
        if not asyncio.iscoroutinefunction(func):
            raise ValueError("Commands must be coroutines")

        perm = default_member_permissions
        if hasattr(func, "default_member_permissions"):
            if perm:
                perm = perm | func.default_member_permissions
            else:
                perm = func.default_member_permissions

        _description = description
        if _description is MISSING:
            _description = func.__doc__ if func.__doc__ else "No Description Set"

        cmd = SlashCommand(
            name=name,
            group_name=group_name,
            group_description=group_description,
            sub_cmd_name=sub_cmd_name,
            sub_cmd_description=sub_cmd_description,
            description=_description,
            scopes=scopes if scopes else [GLOBAL_SCOPE],
            default_member_permissions=perm,
            dm_permission=dm_permission,
            callback=func,
            options=options,
            nsfw=nsfw,
        )

        return cmd

    return wrapper


def subcommand(
    base: str | LocalisedName,
    *,
    subcommand_group: Optional[str | LocalisedName] = None,
    name: Optional[str | LocalisedName] = None,
    description: Absent[str | LocalisedDesc] = MISSING,
    base_description: Optional[str | LocalisedDesc] = None,
    base_desc: Optional[str | LocalisedDesc] = None,
    base_default_member_permissions: Optional["Permissions"] = None,
    base_dm_permission: bool = True,
    subcommand_group_description: Optional[str | LocalisedDesc] = None,
    sub_group_desc: Optional[str | LocalisedDesc] = None,
    scopes: List["Snowflake_Type"] = None,
    options: List[dict] = None,
    nsfw: bool = False,
) -> Callable[[Coroutine], SlashCommand]:
    """
    A decorator specifically tailored for creating subcommands.

    Args:
        base: The name of the base command
        subcommand_group: The name of the subcommand group, if any.
        name: The name of the subcommand, defaults to the name of the coroutine.
        description: The description of the subcommand
        base_description: The description of the base command
        base_desc: An alias of `base_description`
        base_default_member_permissions: What permissions members need to have by default to use this command.
        base_dm_permission: Should this command be available in DMs.
        subcommand_group_description: Description of the subcommand group
        sub_group_desc: An alias for `subcommand_group_description`
        scopes: The scopes of which this command is available, defaults to GLOBAL_SCOPE
        options: The options for this command
        nsfw: This command should only work in NSFW channels

    Returns:
        A SlashCommand object

    """

    def wrapper(func) -> SlashCommand:
        if not asyncio.iscoroutinefunction(func):
            raise ValueError("Commands must be coroutines")

        _description = description
        if _description is MISSING:
            _description = func.__doc__ if func.__doc__ else "No Description Set"

        cmd = SlashCommand(
            name=base,
            description=(base_description or base_desc) or "No Description Set",
            group_name=subcommand_group,
            group_description=(subcommand_group_description or sub_group_desc) or "No Description Set",
            sub_cmd_name=name,
            sub_cmd_description=_description,
            default_member_permissions=base_default_member_permissions,
            dm_permission=base_dm_permission,
            scopes=scopes if scopes else [GLOBAL_SCOPE],
            callback=func,
            options=options,
            nsfw=nsfw,
        )
        return cmd

    return wrapper


def context_menu(
    name: str | LocalisedName,
    context_type: "CommandTypes",
    scopes: Absent[List["Snowflake_Type"]] = MISSING,
    default_member_permissions: Optional["Permissions"] = None,
    dm_permission: bool = True,
) -> Callable[[Coroutine], ContextMenu]:
    """
    A decorator to declare a coroutine as a Context Menu.

    Args:
        name: 1-32 character name of the context menu
        context_type: The type of context menu
        scopes: The scope this command exists within
        default_member_permissions: What permissions members need to have by default to use this command.
        dm_permission: Should this command be available in DMs.

    Returns:
        ContextMenu object

    """

    def wrapper(func) -> ContextMenu:
        if not asyncio.iscoroutinefunction(func):
            raise ValueError("Commands must be coroutines")

        perm = default_member_permissions
        if hasattr(func, "default_member_permissions"):
            if perm:
                perm = perm | func.default_member_permissions
            else:
                perm = func.default_member_permissions

        cmd = ContextMenu(
            name=name,
            type=context_type,
            scopes=scopes if scopes else [GLOBAL_SCOPE],
            default_member_permissions=perm,
            dm_permission=dm_permission,
            callback=func,
        )
        return cmd

    return wrapper


def component_callback(*custom_id: str) -> Callable[[Coroutine], ComponentCommand]:
    """
    Register a coroutine as a component callback.

    Component callbacks work the same way as commands, just using components as a way of invoking, instead of messages.
    Your callback will be given a single argument, `ComponentContext`

    Args:
        *custom_id: The custom ID of the component to wait for

    """

    def wrapper(func) -> ComponentCommand:
        if not asyncio.iscoroutinefunction(func):
            raise ValueError("Commands must be coroutines")

        return ComponentCommand(name=f"ComponentCallback::{custom_id}", callback=func, listeners=custom_id)

    custom_id = _unpack_helper(custom_id)
    return wrapper


def modal_callback(*custom_id: str) -> Callable[[Coroutine], ModalCommand]:
    """
    Register a coroutine as a modal callback.

    Modal callbacks work the same way as commands, just using modals as a way of invoking, instead of messages.
    Your callback will be given a single argument, `ModalContext`

    Args:
        *custom_id: The custom ID of the modal to wait for
    """

    def wrapper(func) -> ModalCommand:
        if not asyncio.iscoroutinefunction(func):
            raise ValueError("Commands must be coroutines")

        return ModalCommand(name=f"ModalCallback::{custom_id}", callback=func, listeners=custom_id)

    custom_id = _unpack_helper(custom_id)
    return wrapper


def slash_option(
    name: str,
    description: str,
    opt_type: Union[OptionTypes, int],
    required: bool = False,
    autocomplete: bool = False,
    choices: List[Union[SlashCommandChoice, dict]] = None,
    channel_types: Optional[list[Union[ChannelTypes, int]]] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
) -> Any:
    r"""
    A decorator to add an option to a slash command.

    Args:
        name: 1-32 lowercase character name matching ^[\w-]{1,32}$
        opt_type: The type of option
        description: 1-100 character description of option
        required: If the parameter is required or optional--default false
        choices: A list of choices the user has to pick between (max 25)
        channel_types: The channel types permitted. The option needs to be a channel
        min_value: The minimum value permitted. The option needs to be an integer or float
        max_value: The maximum value permitted. The option needs to be an integer or float
        min_length: The minimum length of text a user can input. The option needs to be a string
        max_length: The maximum length of text a user can input. The option needs to be a string
    """

    def wrapper(func: Coroutine) -> Coroutine:
        if hasattr(func, "cmd_id"):
            raise Exception("slash_option decorators must be positioned under a slash_command decorator")

        option = SlashCommandOption(
            name=name,
            type=opt_type,
            description=description,
            required=required,
            autocomplete=autocomplete,
            choices=choices if choices else [],
            channel_types=channel_types,
            min_value=min_value,
            max_value=max_value,
            min_length=min_length,
            max_length=max_length,
        )
        if not hasattr(func, "options"):
            func.options = []
        func.options.insert(0, option)
        return func

    return wrapper


def slash_default_member_permission(permission: "Permissions") -> Any:
    """
    A decorator to permissions members need to have by default to use a command.

    Args:
        permission: The permissions to require for to this command

    """

    def wrapper(func: Coroutine) -> Coroutine:
        if hasattr(func, "cmd_id"):
            raise Exception(
                "slash_default_member_permission decorators must be positioned under a slash_command decorator"
            )

        if not hasattr(func, "default_member_permissions") or func.default_member_permissions is None:
            func.default_member_permissions = permission
        else:
            func.default_member_permissions = func.default_member_permissions | permission
        return func

    return wrapper


def auto_defer(ephemeral: bool = False, time_until_defer: float = 0.0) -> Callable[[Coroutine], Coroutine]:
    """
    A decorator to add an auto defer to a application command.

    Args:
        ephemeral: Should the command be deferred as ephemeral
        time_until_defer: How long to wait before deferring automatically

    """

    def wrapper(func: Coroutine) -> Coroutine:
        if hasattr(func, "cmd_id"):
            raise Exception("auto_defer decorators must be positioned under a slash_command decorator")
        func.auto_defer = AutoDefer(enabled=True, ephemeral=ephemeral, time_until_defer=time_until_defer)
        return func

    return wrapper


def application_commands_to_dict(commands: Dict["Snowflake_Type", Dict[str, InteractionCommand]]) -> dict:
    """
    Convert the command list into a format that would be accepted by discord.

    `Client.interactions` should be the variable passed to this

    """
    cmd_bases = {}  # {cmd_base: [commands]}
    """A store of commands organised by their base command"""
    output = {}
    """The output dictionary"""

    def squash_subcommand(subcommands: List) -> Dict:
        output_data = {}
        groups = {}
        sub_cmds = []
        for subcommand in subcommands:
            if not output_data:
                output_data = {
                    "name": str(subcommand.name),
                    "description": str(subcommand.description),
                    "options": [],
                    "default_member_permissions": str(int(subcommand.default_member_permissions))
                    if subcommand.default_member_permissions
                    else None,
                    "dm_permission": subcommand.dm_permission,
                    "name_localizations": subcommand.name.to_locale_dict(),
                    "description_localizations": subcommand.description.to_locale_dict(),
                    "nsfw": subcommand.nsfw,
                }
            if bool(subcommand.group_name):
                if str(subcommand.group_name) not in groups:
                    groups[str(subcommand.group_name)] = {
                        "name": str(subcommand.group_name),
                        "description": str(subcommand.group_description),
                        "type": int(OptionTypes.SUB_COMMAND_GROUP),
                        "options": [],
                        "name_localizations": subcommand.group_name.to_locale_dict(),
                        "description_localizations": subcommand.group_description.to_locale_dict(),
                    }
                groups[str(subcommand.group_name)]["options"].append(
                    subcommand.to_dict() | {"type": int(OptionTypes.SUB_COMMAND)}
                )
            elif subcommand.is_subcommand:
                sub_cmds.append(subcommand.to_dict() | {"type": int(OptionTypes.SUB_COMMAND)})
        options = list(groups.values()) + sub_cmds
        output_data["options"] = options
        return output_data

    for _scope, cmds in commands.items():
        for cmd in cmds.values():
            cmd_name = str(cmd.name)
            if cmd_name not in cmd_bases:
                cmd_bases[cmd_name] = [cmd]
                continue
            if cmd not in cmd_bases[cmd_name]:
                cmd_bases[cmd_name].append(cmd)

    for cmd_list in cmd_bases.values():
        if any(c.is_subcommand for c in cmd_list):
            # validate all commands share required attributes
            scopes: list[Snowflake_Type] = list({s for c in cmd_list for s in c.scopes})
            base_description = next(
                (
                    c.description
                    for c in cmd_list
                    if str(c.description) is not None and str(c.description) != "No Description Set"
                ),
                "No Description Set",
            )
            nsfw = cmd_list[0].nsfw

            if not all(str(c.description) in (str(base_description), "No Description Set") for c in cmd_list):
                logger.warning(
                    f"Conflicting descriptions found in `{cmd_list[0].name}` subcommands; `{str(base_description)}` will be used"
                )
            if not all(c.default_member_permissions == cmd_list[0].default_member_permissions for c in cmd_list):
                raise ValueError(f"Conflicting `default_member_permissions` values found in `{cmd_list[0].name}`")
            if not all(c.dm_permission == cmd_list[0].dm_permission for c in cmd_list):
                raise ValueError(f"Conflicting `dm_permission` values found in `{cmd_list[0].name}`")
            if not all(c.nsfw == nsfw for c in cmd_list):
                logger.warning(f"Conflicting `nsfw` values found in {cmd_list[0].name} - `True` will be used")
                nsfw = True

            for cmd in cmd_list:
                cmd.scopes = list(scopes)
                cmd.description = base_description
            # end validation of attributes
            cmd_data = squash_subcommand(cmd_list)
        else:
            scopes = cmd_list[0].scopes
            cmd_data = cmd_list[0].to_dict()
        for s in scopes:
            if s not in output:
                output[s] = [cmd_data]
                continue
            output[s].append(cmd_data)
    return output


def _compare_commands(local_cmd: dict, remote_cmd: dict) -> bool:
    """
    Compares remote and local commands

    Args:
        local_cmd: The local command
        remote_cmd: The remote command from discord

    Returns:
        True if the commands are the same
    """
    lookup: dict[str, tuple[str, any]] = {
        "name": ("name", ""),
        "description": ("description", ""),
        "default_member_permissions": ("default_member_permissions", None),
        "dm_permission": ("dm_permission", True),
        "name_localized": ("name_localizations", None),
        "description_localized": ("description_localizations", None),
    }

    for local_name, comparison_data in lookup.items():
        remote_name, default_value = comparison_data
        if local_cmd.get(local_name, default_value) != remote_cmd.get(remote_name, default_value):
            return False
    return True


def _compare_options(local_opt_list: dict, remote_opt_list: dict) -> bool:
    options_lookup: dict[str, tuple[str, any]] = {
        "name": ("name", ""),
        "description": ("description", ""),
        "required": ("required", False),
        "autocomplete": ("autocomplete", False),
        "name_localized": ("name_localizations", None),
        "description_localized": ("description_localizations", None),
        "choices": ("choices", []),
        "max_value": ("max_value", None),
        "min_value": ("min_value", None),
        "max_length": ("max_length", None),
        "min_length": ("max_length", None),
    }
    post_process: Dict[str, Callable] = {
        "choices": lambda l: [d | {"name_localizations": {}} if len(d) == 2 else d for d in l],
    }

    if local_opt_list != remote_opt_list:
        if len(local_opt_list) != len(remote_opt_list):
            return False
        for i in range(len(local_opt_list)):
            local_option = local_opt_list[i]
            remote_option = remote_opt_list[i]

            if local_option["type"] == remote_option["type"]:
                if local_option["type"] in (OptionTypes.SUB_COMMAND_GROUP, OptionTypes.SUB_COMMAND):
                    if not _compare_commands(local_option, remote_option) or not _compare_options(
                        local_option.get("options", []), remote_option.get("options", [])
                    ):
                        return False
                else:
                    for local_name, comparison_data in options_lookup.items():
                        remote_name, default_value = comparison_data
                        if local_option.get(local_name, default_value) != post_process.get(remote_name, lambda l: l)(
                            remote_option.get(remote_name, default_value)
                        ):
                            return False

            else:
                return False
    return True


def sync_needed(local_cmd: dict, remote_cmd: Optional[dict] = None) -> bool:
    """
    Compares a local application command to its remote counterpart to determine if a sync is required.

    Args:
        local_cmd: The local json representation of the command
        remote_cmd: The json representation of the command from Discord

    Returns:
        Boolean indicating if a sync is needed
    """
    if not remote_cmd:
        # No remote version, command must be new
        return True

    if not _compare_commands(local_cmd, remote_cmd):
        # basic comparison of attributes
        return True

    if remote_cmd["type"] == CommandTypes.CHAT_INPUT:
        try:
            if not _compare_options(local_cmd["options"], remote_cmd["options"]):
                # options are not the same, sync needed
                return True
        except KeyError:
            if "options" in local_cmd or "options" in remote_cmd:
                return True

    return False
