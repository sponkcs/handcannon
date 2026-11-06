package dev.handcannon;

import io.papermc.paper.event.player.PrePlayerAttackEntityEvent;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.format.NamedTextColor;
import net.kyori.adventure.text.format.TextDecoration;
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
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.persistence.PersistentDataType;
import org.bukkit.scheduler.BukkitRunnable;
import org.bukkit.util.Vector;

import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

/** A nail-studded baseball bat. Heavy, slow swings; a fully charged swing is a home run that sends the target flying. */
final class NailBat implements Listener {
    private final HandCannonPlugin plugin;
    private final NamespacedKey batKey, damageKey, speedKey;
    /** Players whose current swing started fully charged (checked before vanilla resets the attack cooldown). */
    private final Set<UUID> charged = new HashSet<>();

    NailBat(HandCannonPlugin plugin) {
        this.plugin = plugin;
        batKey = new NamespacedKey(plugin, "nail_bat");
        damageKey = new NamespacedKey(plugin, "nail_bat_damage");
        speedKey = new NamespacedKey(plugin, "nail_bat_speed");
    }

    ItemStack create() {
        var cfg = plugin.getConfig();
        ItemStack it = new ItemStack(Material.STICK);
        ItemMeta m = it.getItemMeta();
        m.displayName(Component.text("Nail Bat", NamedTextColor.GOLD).decoration(TextDecoration.ITALIC, false));
        m.lore(List.of(Component.text("Fully charged swings are home runs", NamedTextColor.GRAY).decoration(TextDecoration.ITALIC, false)));
        m.setItemModel(NamespacedKey.fromString("handcannon:nail_bat"));
        m.setMaxStackSize(1);
        // players punch for 1 and swing 4 times a second, so the modifiers are the difference from that
        m.addAttributeModifier(Attribute.ATTACK_DAMAGE, new AttributeModifier(damageKey,
                cfg.getDouble("bat.damage", 9) - 1, AttributeModifier.Operation.ADD_NUMBER, EquipmentSlotGroup.MAINHAND));
        m.addAttributeModifier(Attribute.ATTACK_SPEED, new AttributeModifier(speedKey,
                cfg.getDouble("bat.attack-speed", 0.9) - 4, AttributeModifier.Operation.ADD_NUMBER, EquipmentSlotGroup.MAINHAND));
        m.getPersistentDataContainer().set(batKey, PersistentDataType.BYTE, (byte) 1);
        it.setItemMeta(m);
        return it;
    }

    boolean is(ItemStack it) {
        return it != null && it.hasItemMeta() && it.getItemMeta().getPersistentDataContainer().has(batKey, PersistentDataType.BYTE);
    }

    @EventHandler
    public void onPreAttack(PrePlayerAttackEntityEvent e) {
        Player p = e.getPlayer();
        double need = plugin.getConfig().getDouble("bat.home-run-charge", 0.95);
        if (e.willAttack() && is(p.getInventory().getItemInMainHand()) && p.getAttackCooldown() >= need) charged.add(p.getUniqueId());
        else charged.remove(p.getUniqueId());
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onHit(EntityDamageByEntityEvent e) {
        if (!(e.getDamager() instanceof Player p) || !(e.getEntity() instanceof LivingEntity target)) return;
        if (e.getCause() != EntityDamageEvent.DamageCause.ENTITY_ATTACK || !is(p.getInventory().getItemInMainHand())) return;
        boolean homeRun = charged.remove(p.getUniqueId());
        var w = target.getWorld();
        var at = target.getLocation().add(0, target.getHeight() * 0.6, 0);
        w.playSound(at, Sound.ENTITY_ZOMBIE_ATTACK_WOODEN_DOOR, SoundCategory.PLAYERS, homeRun ? 1.0f : 0.5f, homeRun ? 1.3f : 1.7f);
        if (!homeRun) return;

        var cfg = plugin.getConfig();
        Vector dir = target.getLocation().toVector().subtract(p.getLocation().toVector()).setY(0);
        if (dir.lengthSquared() < 1e-6) dir = p.getLocation().getDirection().setY(0);
        if (dir.lengthSquared() < 1e-6) dir = new Vector(1, 0, 0);
        Vector launch = dir.normalize().multiply(cfg.getDouble("bat.home-run-power", 2.4)).setY(cfg.getDouble("bat.home-run-lift", 1.1));
        w.playSound(at, Sound.ENTITY_FIREWORK_ROCKET_LAUNCH, SoundCategory.PLAYERS, 1.2f, 0.8f);
        w.spawnParticle(Particle.CRIT, at, 30, 0.3, 0.3, 0.3, 0.6);
        w.spawnParticle(Particle.EXPLOSION, at, 1, 0, 0, 0, 0);
        p.sendActionBar(Component.text("HOME RUN!", NamedTextColor.GOLD, TextDecoration.BOLD));

        // launch next tick, after vanilla has applied its own knockback, then leave a cloud trail while it flies
        new BukkitRunnable() {
            int ticks = 0;
            @Override public void run() {
                if (ticks == 0) { if (target.isValid()) target.setVelocity(launch); }
                else if (!target.isValid() || ticks > 40 || (ticks > 6 && target.isOnGround())) { cancel(); return; }
                else w.spawnParticle(Particle.CLOUD, target.getLocation().add(0, target.getHeight() / 2, 0), 2, 0.1, 0.1, 0.1, 0);
                ticks++;
            }
        }.runTaskTimer(plugin, 1, 1);
    }

    // the bat is a stick underneath: keep it out of crafting grids and furnaces
    @EventHandler
    public void onCraft(PrepareItemCraftEvent e) {
        for (ItemStack it : e.getInventory().getMatrix()) if (is(it)) { e.getInventory().setResult(null); return; }
    }

    @EventHandler
    public void onBurn(FurnaceBurnEvent e) { if (is(e.getFuel())) e.setCancelled(true); }
}
