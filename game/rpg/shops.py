"""Merchant shelves shared by the simulation and the trade screen."""

from .. import library

DEFAULTS = {
    "merchant": ["potion_heal_minor", "potion_magicka", "torch", "lockpick",
                 "cloth_robe", "cloth_hood", "sandals", "hide_boots", "copper_ring",
                 "iron_arrow", "bread"],
    "blacksmith": ["iron_longsword", "iron_mace", "steel_longsword", "iron_shield",
                   "iron_cuirass", "iron_helmet", "short_bow", "iron_arrow",
                   "crossbow", "iron_bolt", "chain_shirt", "chain_coif", "scale_mail",
                   "kite_shield", "plate_helm", "plate_armour", "tower_shield", "buckler"],
    "armourer": ["leather_cuirass", "hide_armour", "studded_leather", "chain_shirt",
                 "scale_mail", "plate_armour", "plate_helm", "plate_greaves",
                 "round_shield", "kite_shield"],
}


def stock_for(npc):
    if npc is None:
        return []
    stock = npc.properties.get("stock")
    if isinstance(stock, list) and stock:
        return [{"id": s} if isinstance(s, str) else s for s in stock]
    role = str(npc.properties.get("npc_role", "merchant"))
    shelf = DEFAULTS.get(role, DEFAULTS["merchant"]) + library.shop_books(npc.properties)
    return [{"id": i} for i in shelf]
