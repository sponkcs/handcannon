package dev.handcannon;

import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.format.NamedTextColor;
import net.kyori.adventure.text.format.TextDecoration;
import org.bukkit.Color;
import org.bukkit.Material;
import org.bukkit.NamespacedKey;
import org.bukkit.Particle;
import org.bukkit.Sound;
import org.bukkit.SoundCategory;
import org.bukkit.attribute.Attribute;
import org.bukkit.attribute.AttributeModifier;
import org.bukkit.entity.LivingEntity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.entity.EntityDamageEvent;
import org.bukkit.event.inventory.FurnaceBurnEvent;
import org.bukkit.event.inventory.PrepareItemCraftEvent;
import org.bukkit.inventory.EquipmentSlotGroup;
import org.bukkit.inventory.ItemFlag;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.persistence.PersistentDataType;

import java.util.List;

/** The Holy Blade (internally "radiant_ankh"): a sword whose hilt is an ankh. A melee weapon; every hit flares with light. */
final class RadiantAnkh implements Listener {
    private static final Particle.DustOptions GOLD = new Particle.DustOptions(Color.fromRGB(255, 222, 120), 1.2f);

    private final HandCannonPlugin plugin;
    private final NamespacedKey key;

    RadiantAnkh(HandCannonPlugin plugin) {
        this.plugin = plugin;
        key = new NamespacedKey(plugin, "radiant_ankh");
    }

    ItemStack create() {
        var cfg = plugin.getConfig();
        ItemStack it = new ItemStack(Material.STICK);
        ItemMeta m = it.getItemMeta();
        m.displayName(Component.text("Holy Blade", NamedTextColor.GOLD).decoration(TextDecoration.ITALIC, false));
        m.lore(List.of(Component.text("Light given an edge", NamedTextColor.GRAY).decoration(TextDecoration.ITALIC, false)));
        m.setItemModel(NamespacedKey.fromString("handcannon:radiant_ankh"));
        m.setMaxStackSize(1);
        // vanilla "base" modifier ids, so the tooltip shows the totals like a sword's
        m.addAttributeModifier(Attribute.ATTACK_DAMAGE, new AttributeModifier(NamespacedKey.minecraft("base_attack_damage"),
                cfg.getDouble("holy.damage", 100) - 1, AttributeModifier.Operation.ADD_NUMBER, EquipmentSlotGroup.MAINHAND));
        m.addAttributeModifier(Attribute.ATTACK_SPEED, new AttributeModifier(NamespacedKey.minecraft("base_attack_speed"),
                cfg.getDouble("holy.attack-speed", 1.6) - 4, AttributeModifier.Operation.ADD_NUMBER, EquipmentSlotGroup.MAINHAND));
        m.addItemFlags(ItemFlag.HIDE_ATTRIBUTES);   // keep its damage and swing speed out of the tooltip
        m.getPersistentDataContainer().set(key, PersistentDataType.BYTE, (byte) 1);
        it.setItemMeta(m);
        return it;
    }

    boolean is(ItemStack it) {
        return it != null && it.hasItemMeta() && it.getItemMeta().getPersistentDataContainer().has(key, PersistentDataType.BYTE);
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onHit(EntityDamageByEntityEvent e) {
        if (!(e.getDamager() instanceof Player p) || !(e.getEntity() instanceof LivingEntity target)) return;
        if (e.getCause() != EntityDamageEvent.DamageCause.ENTITY_ATTACK || !is(p.getInventory().getItemInMainHand())) return;
        var at = target.getLocation().add(0, target.getHeight() * 0.6, 0);
        var w = target.getWorld();
        w.spawnParticle(Particle.END_ROD, at, 10, 0.2, 0.3, 0.2, 0.08);
        w.spawnParticle(Particle.DUST, at, 12, 0.3, 0.4, 0.3, 0, GOLD);
        w.playSound(at, Sound.BLOCK_AMETHYST_BLOCK_CHIME, SoundCategory.PLAYERS, 1.2f, 1.4f);
    }

    // a stick underneath: keep it out of crafting grids and furnaces
    @EventHandler
    public void onCraft(PrepareItemCraftEvent e) {
        for (ItemStack it : e.getInventory().getMatrix()) if (is(it)) { e.getInventory().setResult(null); return; }
    }

    @EventHandler
    public void onBurn(FurnaceBurnEvent e) { if (is(e.getFuel())) e.setCancelled(true); }
}
