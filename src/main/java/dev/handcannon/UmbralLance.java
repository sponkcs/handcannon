package dev.handcannon;

import org.bukkit.Color;
import org.bukkit.FluidCollisionMode;
import org.bukkit.GameMode;
import org.bukkit.Location;
import org.bukkit.NamespacedKey;
import org.bukkit.Particle;
import org.bukkit.Sound;
import org.bukkit.SoundCategory;
import org.bukkit.World;
import org.bukkit.entity.Entity;
import org.bukkit.entity.LivingEntity;
import org.bukkit.entity.Player;
import org.bukkit.event.Event;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.block.Action;
import org.bukkit.event.player.PlayerInteractEntityEvent;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.inventory.EquipmentSlot;
import org.bukkit.inventory.ItemStack;
import org.bukkit.persistence.PersistentDataType;
import org.bukkit.potion.PotionEffect;
import org.bukkit.potion.PotionEffectType;
import org.bukkit.util.BoundingBox;
import org.bukkit.util.RayTraceResult;
import org.bukkit.util.Vector;

import java.util.Comparator;
import java.util.List;

/**
 * The Umbral Lance: right-click fires an instant crimson beam that pierces everything in a line up to the first
 * wall. Each target takes damage and is wrapped in Darkness (the pulsing black vision the Warden causes).
 */
final class UmbralLance implements Listener {
    private static final Particle.DustOptions CRIMSON = new Particle.DustOptions(Color.fromRGB(200, 20, 40), 1.4f);
    private static final Particle.DustOptions EMBER = new Particle.DustOptions(Color.fromRGB(255, 70, 80), 0.8f);

    private final HandCannonPlugin plugin;
    private final NamespacedKey key;

    UmbralLance(HandCannonPlugin plugin) {
        this.plugin = plugin;
        key = new NamespacedKey(plugin, "umbral_lance");
    }

    ItemStack create() { return plugin.makeGun(key, "Umbral Lance", "Right-click to loose a beam of darkness", "handcannon:umbral_lance"); }

    boolean is(ItemStack it) {
        return it != null && it.hasItemMeta() && it.getItemMeta().getPersistentDataContainer().has(key, PersistentDataType.BYTE);
    }

    @EventHandler
    public void onInteract(PlayerInteractEvent e) {
        if (e.getAction() != Action.RIGHT_CLICK_AIR && e.getAction() != Action.RIGHT_CLICK_BLOCK) return;
        if (!is(e.getItem())) return;
        e.setUseItemInHand(Event.Result.DENY);
        e.setUseInteractedBlock(Event.Result.DENY);
        Player p = e.getPlayer();
        if (e.getHand() == EquipmentSlot.OFF_HAND && is(p.getInventory().getItemInMainHand())) return;
        fire(p, e.getItem());
    }

    @EventHandler
    public void onInteractEntity(PlayerInteractEntityEvent e) {
        Player p = e.getPlayer();
        ItemStack it = p.getInventory().getItem(e.getHand());
        if (!is(it)) return;
        e.setCancelled(true);
        if (e.getHand() == EquipmentSlot.OFF_HAND && is(p.getInventory().getItemInMainHand())) return;
        fire(p, it);
    }

    private void fire(Player p, ItemStack gun) {
        if (!p.hasPermission("handcannon.use") || p.hasCooldown(gun)) return;
        var cfg = plugin.getConfig();
        p.setCooldown(gun, Math.max(1, cfg.getInt("umbral.cooldown-ticks", 24)));
        double range = cfg.getDouble("umbral.range", 40);
        double damage = cfg.getDouble("umbral.damage", 10);
        int darkness = Math.max(0, cfg.getInt("umbral.darkness-ticks", 100));

        World w = p.getWorld();
        Location eye = p.getEyeLocation();
        Vector dir = eye.getDirection().normalize();

        // the beam stops at the first wall, and runs through every creature before it
        RayTraceResult wall = w.rayTraceBlocks(eye, dir, range, FluidCollisionMode.NEVER, true);
        double length = wall != null ? wall.getHitPosition().distance(eye.toVector()) : range;
        Vector from = eye.toVector(), to = from.clone().add(dir.clone().multiply(length));
        BoundingBox sweep = BoundingBox.of(from, to).expand(1.0);
        List<LivingEntity> hits = w.getNearbyEntities(sweep, ent -> canHit(p, ent)).stream()
                .map(ent -> (LivingEntity) ent)
                .filter(le -> le.getBoundingBox().expand(0.3).rayTrace(from, dir, length) != null)
                .sorted(Comparator.comparingDouble(le -> le.getLocation().distanceSquared(eye)))
                .toList();

        // muzzle, then the beam: a crimson core wrapped in drifting black smoke
        Vector right = dir.clone().crossProduct(new Vector(0, 1, 0));
        if (right.lengthSquared() < 1e-6) right = new Vector(1, 0, 0); else right.normalize();
        Vector muzzle = from.clone().add(dir.clone().multiply(1.4)).add(right.multiply(0.3)).add(new Vector(0, -0.2, 0));
        w.playSound(eye, Sound.ENTITY_WITHER_SHOOT, SoundCategory.PLAYERS, 0.8f, 0.6f);
        w.playSound(eye, Sound.BLOCK_AMETHYST_BLOCK_RESONATE, SoundCategory.PLAYERS, 1.4f, 0.5f);
        w.spawnParticle(Particle.SMOKE, muzzle.toLocation(w), 10, 0.1, 0.1, 0.1, 0.02);
        Vector path = to.clone().subtract(muzzle);
        double len = path.length();
        if (len > 0.01) {
            path.multiply(1 / len);
            for (double d = 0; d < len; d += 0.3) {
                Location at = muzzle.clone().add(path.clone().multiply(d)).toLocation(w);
                w.spawnParticle(Particle.DUST, at, 1, 0.02, 0.02, 0.02, 0, CRIMSON);
                if (d % 1.2 < 0.3) w.spawnParticle(Particle.SMOKE, at, 1, 0.08, 0.08, 0.08, 0.005);
            }
        }
        if (wall != null) {
            Location at = wall.getHitPosition().toLocation(w);
            w.spawnParticle(Particle.DUST, at, 12, 0.15, 0.15, 0.15, 0, EMBER);
            w.spawnParticle(Particle.LARGE_SMOKE, at, 3, 0.1, 0.1, 0.1, 0.01);
        }

        for (LivingEntity target : hits) {
            target.setNoDamageTicks(0);
            target.damage(damage, p);
            if (darkness > 0) target.addPotionEffect(new PotionEffect(PotionEffectType.DARKNESS, darkness, 0, false, true, true));
            Location at = target.getLocation().add(0, target.getHeight() / 2, 0);
            w.spawnParticle(Particle.SOUL, at, 6, 0.25, 0.4, 0.25, 0.02);
            w.spawnParticle(Particle.DUST, at, 10, 0.25, 0.4, 0.25, 0, EMBER);
            w.playSound(at, Sound.ENTITY_WARDEN_HEARTBEAT, SoundCategory.PLAYERS, 1f, 0.8f);
        }
    }

    private static boolean canHit(Player shooter, Entity ent) {
        if (ent == shooter || !(ent instanceof LivingEntity le) || le.isDead()) return false;
        return !(ent instanceof Player pl && pl.getGameMode() == GameMode.SPECTATOR);
    }
}
