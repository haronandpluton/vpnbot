from collections.abc import Mapping

from aiogram.types import MessageEntity


GIFT_CUSTOM_EMOJI_ID = "5203996991054432397"
ROBOT_CUSTOM_EMOJI_ID = "5287684458881756303"
SPARKLE_CUSTOM_EMOJI_ID = "5325547803936572038"
STAR_CUSTOM_EMOJI_ID = "5438496463044752972"

DEFAULT_CUSTOM_EMOJI_IDS: Mapping[str, str] = {
    "🎁": GIFT_CUSTOM_EMOJI_ID,
    "🤖": ROBOT_CUSTOM_EMOJI_ID,
    "✨": SPARKLE_CUSTOM_EMOJI_ID,
    "⭐": STAR_CUSTOM_EMOJI_ID,
}


def build_custom_emoji_entities(
    text: str,
    emoji_ids: Mapping[str, str] | None = None,
) -> list[MessageEntity]:
    resolved_ids = (
        DEFAULT_CUSTOM_EMOJI_IDS
        if emoji_ids is None
        else emoji_ids
    )

    entities: list[MessageEntity] = []
    utf16_offset = 0

    for character in text:
        utf16_length = (
            len(character.encode("utf-16-le")) // 2
        )
        custom_emoji_id = resolved_ids.get(character)

        if custom_emoji_id is not None:
            entities.append(
                MessageEntity(
                    type="custom_emoji",
                    offset=utf16_offset,
                    length=utf16_length,
                    custom_emoji_id=custom_emoji_id,
                )
            )

        utf16_offset += utf16_length

    return entities
