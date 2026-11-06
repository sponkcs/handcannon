package dev.handcannon;

import io.papermc.paper.datacomponent.DataComponentTypes;
import io.papermc.paper.datacomponent.item.Consumable;
import io.papermc.paper.datacomponent.item.consumable.ItemUseAnimation;
import io.papermc.paper.event.player.PlayerStopUsingItemEvent;
import net.kyori.adventure.key.Key;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.format.NamedTextColor;
import net.kyori.adventure.text.format.TextDecoration;
import org.bukkit.GameMode;
import org.bukkit.Material;
import org.bukkit.NamespacedKey;
import org.bukkit.Particle;
import org.bukkit.Sound;
import org.bukkit.SoundCategory;
import org.bukkit.attribute.Attribute;
import org.bukkit.attribute.AttributeModifier;
import org.bukkit.entity.Entity;
import org.bukkit.entity.LivingEntity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.block.Action;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.entity.EntityDamageEvent;
import org.bukkit.event.inventory.FurnaceBurnEvent;
import org.bukkit.event.inventory.PrepareItemCraftEvent;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.inventory.EquipmentSlotGroup;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.persistence.PersistentDataType;
import org.bukkit.scheduler.BukkitRunnable;
import org.bukkit.util.RayTraceResult;
import org.bukkit.util.Vector;

import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

/**
 * A nail-studded baseball bat. Left-click is a normal hit. Holding right-click winds up a swing (the bat is raised
 * like a trident); once it is fully charged, letting go swings a home run that sends whatever is in front flying.
 */
final class NailBat implements Listener {
    private final HandCannonPlugin plugin;
    private final NamespacedKey batKey, damageKey, speedKey;
    /** Players currently winding up, so a second right-click event doesn't start a second charge meter. */
    private final Set<UUID> winding = new HashSet<>();
    /** Set while a home run is dealing its damage, so the normal-hit sound doesn't also play. */
    private final Set<UUID> swingingHomeRun = new HashSet<>();

    NailBat(HandCannonPlugin plugin) {
        this.plugin = plugin;
        batKey = new NamespacedKey(plugin, "nail_bat");
        damageKey = NamespacedKey.minecraft("base_attack_damage");
        speedKey = NamespacedKey.minecraft("base_attack_speed");
    }

    ItemStack create() {
        var cfg = plugin.getConfig();
        ItemStack it = new ItemStack(Material.STICK);
        // "using" the bat is what holds it up during the wind-up: it never finishes (an hour) and makes no sound
        it.setData(DataComponentTypes.CONSUMABLE, Consumable.consumable()
                .consumeSeconds(3600f)
                .animation(ItemUseAnimation.SPEAR)
                .sound(Key.key("minecraft", "intentionally_empty"))
                .hasConsumeParticles(false)
                .build());
        ItemMeta m = it.getItemMeta();
        m.displayName(Component.text("Nail Bat", NamedTextColor.RED).decoration(TextDecoration.ITALIC, false));
        m.lore(List.of(Component.text("Batter up!", NamedTextColor.GRAY).decoration(TextDecoration.ITALIC, false)));
        m.setItemModel(NamespacedKey.fromString("handcannon:nail_bat"));
        m.setMaxStackSize(1);
        // players punch for 1 and swing 4 times a second, so the modifiers are the difference from that. Using the
        // vanilla "base" modifier ids makes the tooltip show the totals (like a sword) rather than the differences.
        m.addAttributeModifier(Attribute.ATTACK_DAMAGE, new AttributeModifier(damageKey,
                cfg.getDouble("bat.damage", 10) - 1, AttributeModifier.Operation.ADD_NUMBER, EquipmentSlotGroup.MAINHAND));
        m.addAttributeModifier(Attribute.ATTACK_SPEED, new AttributeModifier(speedKey,
                cfg.getDouble("bat.attack-speed", 0.9) - 4, AttributeModifier.Operation.ADD_NUMBER, EquipmentSlotGroup.MAINHAND));
        m.getPersistentDataContainer().set(batKey, PersistentDataType.BYTE, (byte) 1);
        it.setItemMeta(m);
        return it;
    }

    boolean is(ItemStack it) {
        return it != null && it.hasItemMeta() && it.getItemMeta().getPersistentDataContainer().has(batKey, PersistentDataType.BYTE);
    }

    private int chargeTicks() { return Math.max(1, plugin.getConfig().getInt("bat.charge-ticks", 20)); }

    // ---------------------------------------------------------------- left-click: a normal hit

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onHit(EntityDamageByEntityEvent e) {
        if (!(e.getDamager() instanceof Player p) || !(e.getEntity() instanceof LivingEntity target)) return;
        if (e.getCause() != EntityDamageEvent.DamageCause.ENTITY_ATTACK || swingingHomeRun.contains(p.getUniqueId())) return;
        if (!is(p.getInventory().getItemInMainHand())) return;
        target.getWorld().playSound(target.getLocation().add(0, target.getHeight() * 0.6, 0),
                Sound.ENTITY_ZOMBIE_ATTACK_WOODEN_DOOR, SoundCategory.PLAYERS, 0.5f, 1.7f);
    }

    // ---------------------------------------------------------------- right-click: wind up, release to swing

    @EventHandler
    public void onStartWindUp(PlayerInteractEvent e) {
        if (e.getAction() != Action.RIGHT_CLICK_AIR && e.getAction() != Action.RIGHT_CLICK_BLOCK) return;
        Player p = e.getPlayer();
        if (!is(e.getItem()) || !winding.add(p.getUniqueId())) return;
        int need = chargeTicks();
        new BukkitRunnable() {
            int waited = 0, held = 0;
            @Override public void run() {
                boolean using = p.isOnline() && p.hasActiveItem() && is(p.getActiveItem());
                if (!using) {   // the use may take a tick to start; after that, not using means it's over
                    if (held > 0 || ++waited > 3) { winding.remove(p.getUniqueId()); cancel(); }
                    return;
                }
                if (++held == need) {   // fully wound up
                    p.playSound(p, Sound.BLOCK_NOTE_BLOCK_PLING, SoundCategory.PLAYERS, 0.8f, 1.6f);
                    p.getWorld().spawnParticle(Particle.CRIT, p.getLocation().add(0, 1.8, 0), 8, 0.3, 0.2, 0.3, 0.1);
                }
            }
        }.runTaskTimer(plugin, 1, 1);
    }

    @EventHandler
    public void onRelease(PlayerStopUsingItemEvent e) {
        Player p = e.getPlayer();
        if (!is(e.getItem())) return;
        winding.remove(p.getUniqueId());
        var w = p.getWorld();
        p.swingMainHand();
        if (e.getTicksHeldFor() < chargeTicks()) {   // let go too early: a half-hearted wave, no swing
            w.playSound(p, Sound.ENTITY_PLAYER_ATTACK_NODAMAGE, SoundCategory.PLAYERS, 0.6f, 1.2f);
            return;
        }
        w.playSound(p, Sound.ENTITY_PLAYER_ATTACK_SWEEP, SoundCategory.PLAYERS, 1f, 0.7f);

        var cfg = plugin.getConfig();
        var eye = p.getEyeLocation();
        RayTraceResult hit = w.rayTraceEntities(eye, eye.getDirection(), cfg.getDouble("bat.home-run-reach", 3.5), 0.6,
                ent -> canHit(p, ent));
        if (hit == null || !(hit.getHitEntity() instanceof LivingEntity target)) return;   // swung and missed

        swingingHomeRun.add(p.getUniqueId());
        try {
            target.setNoDamageTicks(0);
            target.damage(cfg.getDouble("bat.home-run-damage", 10), p);
        } finally {
            swingingHomeRun.remove(p.getUniqueId());
        }

        var at = target.getLocation().add(0, target.getHeight() * 0.6, 0);
        Vector dir = target.getLocation().toVector().subtract(p.getLocation().toVector()).setY(0);
        if (dir.lengthSquared() < 1e-6) dir = eye.getDirection().setY(0);
        if (dir.lengthSquared() < 1e-6) dir = new Vector(1, 0, 0);
        Vector launch = dir.normalize().multiply(cfg.getDouble("bat.home-run-power", 2.4)).setY(cfg.getDouble("bat.home-run-lift", 1.1));
        w.playSound(at, Sound.ENTITY_ZOMBIE_ATTACK_WOODEN_DOOR, SoundCategory.PLAYERS, 1.0f, 1.3f);
        w.playSound(at, Sound.ENTITY_FIREWORK_ROCKET_LAUNCH, SoundCategory.PLAYERS, 1.2f, 0.8f);
        w.spawnParticle(Particle.EXPLOSION, at, 1, 0, 0, 0, 0);

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

    private static boolean canHit(Player p, Entity ent) {
        if (ent == p || !(ent instanceof LivingEntity le) || le.isDead()) return false;
        return !(ent instanceof Player pl && pl.getGameMode() == GameMode.SPECTATOR);
    }

    // the bat is a stick underneath: keep it out of crafting grids and furnaces
    @EventHandler
    public void onCraft(PrepareItemCraftEvent e) {
        for (ItemStack it : e.getInventory().getMatrix()) if (is(it)) { e.getInventory().setResult(null); return; }
    }

    @EventHandler
    public void onBurn(FurnaceBurnEvent e) { if (is(e.getFuel())) e.setCancelled(true); }
}
