package dev.handcannon;

import org.bukkit.Bukkit;
import org.bukkit.Color;
import org.bukkit.FluidCollisionMode;
import org.bukkit.GameMode;
import org.bukkit.Location;
import org.bukkit.NamespacedKey;
import org.bukkit.Particle;
import org.bukkit.Sound;
import org.bukkit.SoundCategory;
import org.bukkit.World;
import org.bukkit.attribute.Attribute;
import org.bukkit.attribute.AttributeInstance;
import org.bukkit.attribute.AttributeModifier;
import org.bukkit.entity.Entity;
import org.bukkit.entity.LivingEntity;
import org.bukkit.entity.Mob;
import org.bukkit.entity.Player;
import org.bukkit.event.Event;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.block.Action;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.player.PlayerInteractEntityEvent;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.inventory.EquipmentSlot;
import org.bukkit.inventory.EquipmentSlotGroup;
import org.bukkit.inventory.ItemStack;
import org.bukkit.scheduler.BukkitRunnable;
import org.bukkit.util.RayTraceResult;
import org.bukkit.util.Vector;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * The Pala-Pistol: right-click fires a slow, glowing bolt of yellow light. Whatever it hits takes damage and is
 * stunned for a few seconds: it can't move, jump or attack.
 */
final class PalaPistol implements Listener {
    private static final Particle.DustOptions LIGHT = new Particle.DustOptions(Color.fromRGB(255, 232, 70), 1.6f);
    private static final Particle.DustOptions LIGHT_SMALL = new Particle.DustOptions(Color.fromRGB(255, 246, 150), 0.9f);

    private final HandCannonPlugin plugin;
    private final NamespacedKey key, stunKey;
    /** Stunned entity -> server tick the stun ends. */
    private final Map<UUID, Integer> stunnedUntil = new HashMap<>();
    /** Mobs we switched off ourselves, so we only switch back on the ones we turned off. */
    private final Set<UUID> madeUnaware = new HashSet<>();

    PalaPistol(HandCannonPlugin plugin) {
        this.plugin = plugin;
        key = new NamespacedKey(plugin, "pala_pistol");
        stunKey = new NamespacedKey(plugin, "pala_stun");
    }

    ItemStack create() { return plugin.makeGun(key, "Pala-Pistol", "Right-click to fire a stunning bolt of light", "handcannon:pala_pistol"); }

    boolean is(ItemStack it) {
        return it != null && it.hasItemMeta() && it.getItemMeta().getPersistentDataContainer().has(key, org.bukkit.persistence.PersistentDataType.BYTE);
    }

    // ---------------------------------------------------------------- triggers

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

    // ---------------------------------------------------------------- the bolt

    private void fire(Player p, ItemStack gun) {
        if (!p.hasPermission("handcannon.use") || p.hasCooldown(gun)) return;
        var cfg = plugin.getConfig();
        p.setCooldown(gun, Math.max(1, cfg.getInt("pala.cooldown-ticks", 12)));
        double speed = Math.max(0.1, cfg.getDouble("pala.speed", 0.8));      // blocks per tick
        double range = cfg.getDouble("pala.range", 48);
        double damage = cfg.getDouble("pala.damage", 10);
        int stunTicks = Math.max(1, cfg.getInt("pala.stun-ticks", 60));

        World w = p.getWorld();
        Location eye = p.getEyeLocation();
        Vector dir = eye.getDirection().normalize();
        Vector right = dir.clone().crossProduct(new Vector(0, 1, 0));
        if (right.lengthSquared() < 1e-6) right = new Vector(1, 0, 0); else right.normalize();
        Location start = eye.clone().add(dir.clone().multiply(1.0)).add(right.multiply(0.3)).add(0, -0.2, 0);

        w.playSound(start, Sound.ENTITY_ILLUSIONER_CAST_SPELL, SoundCategory.PLAYERS, 0.9f, 1.8f);
        w.playSound(start, Sound.BLOCK_AMETHYST_BLOCK_CHIME, SoundCategory.PLAYERS, 1.2f, 1.6f);
        w.spawnParticle(Particle.DUST, start, 8, 0.08, 0.08, 0.08, 0, LIGHT);

        new BukkitRunnable() {
            final Vector pos = start.toVector();
            double travelled = 0;
            @Override public void run() {
                if (!p.isOnline() && travelled == 0) { cancel(); return; }
                double step = Math.min(speed, range - travelled);
                Location here = pos.toLocation(w);
                RayTraceResult hit = w.rayTrace(here, dir, step, FluidCollisionMode.NEVER, true, 0.35, ent -> canHit(p, ent));
                if (hit != null) {
                    Location at = hit.getHitPosition().toLocation(w);
                    if (hit.getHitEntity() instanceof LivingEntity target) {
                        target.setNoDamageTicks(0);
                        target.damage(damage, p);
                        stun(target, stunTicks);
                        w.playSound(at, Sound.BLOCK_BEACON_DEACTIVATE, SoundCategory.PLAYERS, 1f, 1.8f);
                    } else {
                        w.playSound(at, Sound.BLOCK_AMETHYST_BLOCK_BREAK, SoundCategory.PLAYERS, 0.8f, 1.6f);
                    }
                    burst(w, at);
                    cancel();
                    return;
                }
                // draw the bolt along this tick's stretch: a bright head with a soft trail
                for (double d = 0; d < step; d += 0.25)
                    w.spawnParticle(Particle.DUST, pos.clone().add(dir.clone().multiply(d)).toLocation(w), 1, 0.02, 0.02, 0.02, 0, LIGHT);
                pos.add(dir.clone().multiply(step));
                Location head = pos.toLocation(w);
                w.spawnParticle(Particle.DUST, head, 3, 0.06, 0.06, 0.06, 0, LIGHT_SMALL);
                w.spawnParticle(Particle.END_ROD, head, 1, 0, 0, 0, 0);
                travelled += step;
                if (travelled >= range || !head.isChunkLoaded()) {   // fizzles out at the end of its range
                    burst(w, head);
                    cancel();
                }
            }
        }.runTaskTimer(plugin, 0, 1);
    }

    private static void burst(World w, Location at) {
        w.spawnParticle(Particle.DUST, at, 16, 0.25, 0.25, 0.25, 0, LIGHT);
        w.spawnParticle(Particle.END_ROD, at, 6, 0.1, 0.1, 0.1, 0.05);
        w.spawnParticle(Particle.END_ROD, at, 10, 0.05, 0.05, 0.05, 0.12);
    }

    private static boolean canHit(Player shooter, Entity ent) {
        if (ent == shooter || !(ent instanceof LivingEntity le) || le.isDead()) return false;
        return !(ent instanceof Player pl && pl.getGameMode() == GameMode.SPECTATOR);
    }

    // ---------------------------------------------------------------- stun

    private void stun(LivingEntity target, int ticks) {
        UUID id = target.getUniqueId();
        int until = Bukkit.getCurrentTick() + ticks;
        boolean already = stunnedUntil.containsKey(id);
        stunnedUntil.put(id, until);   // a fresh hit just extends a running stun
        if (already) return;

        // can't walk or jump: speed and jump strength drop to zero (transient, so never saved with the entity)
        for (Attribute a : new Attribute[]{Attribute.MOVEMENT_SPEED, Attribute.JUMP_STRENGTH, Attribute.FLYING_SPEED}) {
            AttributeInstance inst = target.getAttribute(a);
            if (inst != null && inst.getModifier(stunKey) == null)
                inst.addTransientModifier(new AttributeModifier(stunKey, -1, AttributeModifier.Operation.MULTIPLY_SCALAR_1, EquipmentSlotGroup.ANY));
        }
        target.setVelocity(new Vector(0, Math.min(0, target.getVelocity().getY()), 0));
        // mobs stop thinking (no pathing, no attacks) but still fall and get pushed
        if (target instanceof Mob mob && mob.isAware()) { mob.setAware(false); madeUnaware.add(id); }

        new BukkitRunnable() {
            int t = 0;
            @Override public void run() {
                Integer end = stunnedUntil.get(id);
                if (!target.isValid() || end == null || Bukkit.getCurrentTick() >= end) {
                    unstun(target);
                    cancel();
                    return;
                }
                if (t++ % 3 == 0) {   // yellow sparks dancing round the head
                    Location head = target.getLocation().add(0, target.getHeight() + 0.2, 0);
                    target.getWorld().spawnParticle(Particle.DUST, head, 3, 0.3, 0.1, 0.3, 0, LIGHT_SMALL);
                    target.getWorld().spawnParticle(Particle.ELECTRIC_SPARK, head, 2, 0.3, 0.1, 0.3, 0.02);
                }
            }
        }.runTaskTimer(plugin, 1, 1);
    }

    private void unstun(LivingEntity target) {
        UUID id = target.getUniqueId();
        stunnedUntil.remove(id);
        for (Attribute a : new Attribute[]{Attribute.MOVEMENT_SPEED, Attribute.JUMP_STRENGTH, Attribute.FLYING_SPEED}) {
            AttributeInstance inst = target.getAttribute(a);
            if (inst != null) inst.removeModifier(stunKey);
        }
        if (madeUnaware.remove(id) && target instanceof Mob mob) mob.setAware(true);
    }

    /** Stunned things can't hit anything. */
    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onStunnedAttack(EntityDamageByEntityEvent e) {
        if (stunnedUntil.containsKey(e.getDamager().getUniqueId())) e.setCancelled(true);
    }

    /** Called when the plugin shuts down: nothing stays frozen. */
    void releaseAll() {
        for (UUID id : Set.copyOf(stunnedUntil.keySet())) {
            Entity ent = Bukkit.getEntity(id);
            if (ent instanceof LivingEntity le) unstun(le);
        }
        stunnedUntil.clear();
        madeUnaware.clear();
    }
}
