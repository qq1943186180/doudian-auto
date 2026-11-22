from copy import deepcopy

import pytest

from doudian_auto.errors import DoudianError
from doudian_auto.workflow import compare_protected
from test_preflight import _snapshot


def pair():
    before = _snapshot({'product_id': '3850071689249554608'})
    options = [{'type': 'checkbox', 'name': '', 'value': name, 'checked': False, 'disabled': False}
               for name in ('靴筒围(cm)', '鞋底厚(cm)', '靴筒高(cm)', '鞋跟高(cm)')]
    price = {'type': 'text', 'name': 'price', 'value': '10.00', 'checked': None, 'disabled': False}
    before['protected'][1]['inputs'] = [price, *deepcopy(options)]
    before['protected'].append({'section': 'goodsEditScrollContainer-尺码表', 'observation': 'ready',
                                'inputs': deepcopy(options), 'selections': [], 'static_fields': [], 'images': []})
    after = deepcopy(before)
    after['protected'][1]['inputs'][1:] = list(reversed(after['protected'][1]['inputs'][1:]))
    after['protected'][-1]['inputs'].reverse()
    return before, after


def test_only_measured_inactive_options_can_reorder_without_mutating_evidence():
    before, after = pair()
    originals = deepcopy((before, after))
    compare_protected(before, after)
    assert (before, after) == originals


@pytest.mark.parametrize('change', ['selected', 'disabled', 'missing', 'duplicate', 'extra_field',
                                   'price', 'interleaved', 'other_section', 'no_full_sku', 'changed_sku'])
def test_size_option_order_never_waives_real_changes_or_missing_evidence(change):
    before, after = pair()
    inputs = after['protected'][1]['inputs']
    if change == 'selected':
        inputs[1]['checked'] = True
    elif change == 'disabled':
        inputs[1]['disabled'] = True
    elif change == 'missing':
        inputs.pop()
    elif change == 'duplicate':
        inputs[1]['value'] = inputs[2]['value']
    elif change == 'extra_field':
        inputs[1]['unobserved_property'] = 'new'
    elif change == 'price':
        inputs[0]['value'] = '99.00'
    elif change == 'interleaved':
        inputs.insert(2, inputs.pop(0))
    elif change == 'other_section':
        before['protected'][-1]['section'] = after['protected'][-1]['section'] = 'other_section'
    elif change == 'no_full_sku':
        before.pop('sku_evidence');after.pop('sku_evidence')
    elif change == 'changed_sku':
        after['sku_evidence']['rows'][0]['price'] = '99'
    with pytest.raises(DoudianError):
        compare_protected(before, after)


def white_bg_mirror_pair():
    before = _snapshot({'product_id': '3815575712589545584'})
    m34 = [
        'https://p9-aio.ecombdimg.com/ecom-shop-material/jpeg_m_60c4efb629c0c24bd0c3abd6cd23e5a9_sx_168459_www600-800~tplv-qzsgku4lz6-fxg-image:0:q75.avis',
        'https://p9-aio.ecombdimg.com/ecom-shop-material/jpeg_m_ff5e82ec084891b93350020eb73897b4_sx_180729_www600-800~tplv-qzsgku4lz6-fxg-image:0:q75.avis',
        'https://p9-aio.ecombdimg.com/ecom-shop-material/jpeg_m_ca323525a49a346f118826fcd7e13b17_sx_150089_www600-800~tplv-qzsgku4lz6-fxg-image:0:q75.avis',
        'https://p3-aio.ecombdimg.com/ecom-shop-material/jpeg_m_d47292924463eac2090ecd60fe9ee206_sx_138661_www600-800~tplv-qzsgku4lz6-fxg-image:0:q75.avis',
    ]
    before['mains'] = [
        'https://p9-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_a3a3cd565770b06b87c474373f31eb5c_sx_167165_www800-800',
        'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_82ee189fd75c894f4799255c200a9435_sx_118156_www800-800',
        'https://p9-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_36ba0bc21fb074cb1effef64a63234e3_sx_111107_www828-828',
        'https://p9-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_9e5a9350740e08717524670c7944fc93_sx_154542_www1199-1199',
    ]
    before['protected'].append({
        'section': 'goodsEditScrollContainer-图文信息',
        'observation': 'ready',
        'inputs': [],
        'selections': [],
        'static_fields': [{'field': '主图视频', 'text': '主图视频'}],
        'images': deepcopy(m34),
    })
    after = deepcopy(before)
    new_main3 = 'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_3a0369ebc34e2f7bd36b96e47f7a93f1_sx_1468111_www1254-1254'
    new_main3_avis = 'https://p3-aio.ecombdimg.com/ecom-shop-material/png_m_3a0369ebc34e2f7bd36b96e47f7a93f1_sx_1468111_www1254-1254~tplv-qzsgku4lz6-fxg-image:0:q75.avis'
    after['mains'] = [
        'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_84b467c3d3bc51f3887a4c166fa8ebfe_sx_971697_www1024-1024',
        'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_a4985631edef3766575182896fac4721_sx_1272977_www1024-1024',
        new_main3,
        'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_4938ce26c5d91774dc42368d4d65f4b8_sx_1465177_www1024-1024',
    ]
    media_after = after['protected'][-1]
    media_after['images'] = [*deepcopy(m34), new_main3_avis]
    media_after['main_34_images'] = [u.replace('https://p9-aio.', 'https://p3-aio.') for u in m34]
    media_after['white_background_images'] = [new_main3_avis]
    return before, after


def test_accepts_verified_new_main_auto_mirrored_into_empty_white_background():
    before, after = white_bg_mirror_pair()
    originals = deepcopy((before, after))
    compare_protected(before, after)
    assert (before, after) == originals


@pytest.mark.parametrize(
    'case',
    [
        'deleted_34',
        'replaced_34',
        'reordered_34',
        'added_to_34_instead_of_wb',
        'moved_between_34_and_wb',
        'pre_existing_wb',
        'two_additions',
        'inserted_before_end',
        'unknown_appended_image',
        'old_main_appended',
        'missing_field_attribution',
        'other_field_changed_in_media',
    ],
)
def test_white_background_mirror_rejects_any_unsafe_or_unattributed_change(case):
    before, after = white_bg_mirror_pair()
    media_before = before['protected'][-1]
    media_after = after['protected'][-1]
    if case == 'deleted_34':
        media_after['images'].pop(0)
        media_after['main_34_images'].pop(0)
    elif case == 'replaced_34':
        other = 'https://p3-aio.ecombdimg.com/ecom-shop-material/jpeg_m_00000000000000000000000000000000_sx_1_www600-800'
        media_after['images'][0] = other
        media_after['main_34_images'][0] = other
    elif case == 'reordered_34':
        media_after['images'][0], media_after['images'][1] = media_after['images'][1], media_after['images'][0]
        media_after['main_34_images'][0], media_after['main_34_images'][1] = (
            media_after['main_34_images'][1],
            media_after['main_34_images'][0],
        )
    elif case == 'added_to_34_instead_of_wb':
        media_after['main_34_images'].append(media_after['white_background_images'].pop())
    elif case == 'moved_between_34_and_wb':
        media_after['images'] = deepcopy(media_before['images'])
        media_after['white_background_images'] = [media_after['main_34_images'].pop()]
        # Even if an extra new main was added to 3:4 and old 3:4 moved to wb:
        new_wb = media_after['white_background_images'][0]
        media_after['images'] = [*media_after['main_34_images'], after['mains'][2], new_wb]
    elif case == 'pre_existing_wb':
        media_before['white_background_images'] = [media_before['images'][-1]]
    elif case == 'two_additions':
        extra = after['mains'][0]
        media_after['images'].append(extra)
        media_after['white_background_images'].append(extra)
    elif case == 'inserted_before_end':
        wb_img = media_after['images'].pop()
        media_after['images'].insert(0, wb_img)
    elif case == 'unknown_appended_image':
        stranger = 'https://p3-aio.ecombdimg.com/ecom-shop-material/png_m_ffffffffffffffffffffffffffffffff_sx_9_www1000-1000'
        media_after['images'][-1] = stranger
        media_after['white_background_images'] = [stranger]
    elif case == 'old_main_appended':
        old_main = before['mains'][0]
        after['mains'][2] = old_main
        media_after['images'][-1] = old_main
        media_after['white_background_images'] = [old_main]
    elif case == 'missing_field_attribution':
        media_after.pop('white_background_images')
    elif case == 'other_field_changed_in_media':
        media_after['static_fields'][0]['text'] = '被篡改的视频说明'
    with pytest.raises(DoudianError):
        compare_protected(before, after)
