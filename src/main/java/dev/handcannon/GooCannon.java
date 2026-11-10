package dev.handcannon;

import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.format.NamedTextColor;
import org.bukkit.Bukkit;
import org.bukkit.GameMode;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.NamespacedKey;
import org.bukkit.Particle;
import org.bukkit.Sound;
import org.bukkit.SoundCategory;
import org.bukkit.World;
import org.bukkit.attribute.Attribute;
import org.bukkit.attribute.AttributeInstance;
import org.bukkit.attribute.AttributeModifier;
import org.bukkit.entity.BlockDisplay;
import org.bukkit.entity.Entity;
import org.bukkit.entity.LivingEntity;
import org.bukkit.entity.Mob;
import org.bukkit.entity.Player;
import org.bukkit.entity.Snowball;
import org.bukkit.event.Event;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.block.Action;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.entity.ProjectileHitEvent;
import org.bukkit.event.player.PlayerInteractEntityEvent;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.player.PlayerToggleSneakEvent;
import org.bukkit.inventory.EquipmentSlot;
import org.bukkit.inventory.EquipmentSlotGroup;
import org.bukkit.inventory.ItemStack;
import org.bukkit.persistence.PersistentDataType;
import org.bukkit.scheduler.BukkitRunnable;
import org.bukkit.util.Transformation;
import org.bukkit.util.Vector;
import org.joml.AxisAngle4f;
import org.joml.Vector3f;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * The Goo Cannon: right-click lobs a glob of honey. It does no damage; whatever it hits is encased in goo and
 * can't move, jump or fall for a few seconds. A trapped player can mash Shift to break out early.
 */
final class GooCannon implements Listener {
    private final HandCannonPlugin plugin;
    private final NamespacedKey key, globKey, trapKey;
    private final Map<UUID, Trap> trapped = new HashMap<>();
    private final Set<UUID> madeUnaware = new HashSet<>();

    /** One goo trap: when it ends, the goo shell shown round the target, and how many Shift presses so far. */
    private static final class Trap {
        int until, presses;
        BlockDisplay shell;
    }

    GooCannon(HandCannonPlugin plugin) {
        this.plugin = plugin;
        key = new NamespacedKey(plugin, "goo_cannon");
        globKey = new NamespacedKey(plugin, "goo_glob");
        trapKey = new NamespacedKey(plugin, "goo_trap");
    }

    ItemStack create() { return plugin.makeGun(key, "Goo Cannon", "Right-click to lob a glob of goo", "handcannon:goo_cannon"); }

    boolean is(ItemStack it) {
        return it != null && it.hasItemMeta() && it.getItemMeta().getPersistentDataContainer().has(key, PersistentDataType.BYTE);
    }

    private boolean isGlob(Entity e) {
        return e instanceof Snowball && e.getPersistentDataContainer().has(globKey, PersistentDataType.BYTE);
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

    // ---------------------------------------------------------------- the glob

    private void fire(Player p, ItemStack gun) {
        if (!p.hasPermission("handcannon.use") || p.hasCooldown(gun)) return;
        var cfg = plugin.getConfig();
        p.setCooldown(gun, Math.max(1, cfg.getInt("goo.cooldown-ticks", 20)));
        Vector vel = p.getEyeLocation().getDirection().normalize().multiply(cfg.getDouble("goo.speed", 1.4));
        Snowball glob = p.launchProjectile(Snowball.class, vel);
        glob.setItem(new ItemStack(Material.HONEY_BLOCK));   // it flies as a little honey block
        glob.getPersistentDataContainer().set(globKey, PersistentDataType.BYTE, (byte) 1);

        World w = p.getWorld();
        w.playSound(p.getLocation(), Sound.ENTITY_SLIME_SQUISH, SoundCategory.PLAYERS, 1f, 0.6f);
        w.playSound(p.getLocation(), Sound.BLOCK_HONEY_BLOCK_PLACE, SoundCategory.PLAYERS, 1f, 0.7f);
        new BukkitRunnable() {   // drippy trail
            int t = 0;
            @Override public void run() {
                if (!glob.isValid() || t++ > 200) { cancel(); return; }
                w.spawnParticle(Particle.FALLING_HONEY, glob.getLocation(), 2, 0.08, 0.08, 0.08, 0);
            }
        }.runTaskTimer(plugin, 1, 1);
    }

    /** The glob itself does no damage or knockback. */
    @EventHandler(priority = EventPriority.LOWEST)
    public void onGlobDamage(EntityDamageByEntityEvent e) {
        if (isGlob(e.getDamager())) e.setCancelled(true);
    }

    @EventHandler
    public void onGlobHit(ProjectileHitEvent e) {
        if (!isGlob(e.getEntity())) return;
        Location at = e.getEntity().getLocation();
        World w = at.getWorld();
        w.spawnParticle(Particle.BLOCK, at, 30, 0.3, 0.3, 0.3, 0, Material.HONEY_BLOCK.createBlockData());
        w.playSound(at, Sound.BLOCK_HONEY_BLOCK_BREAK, SoundCategory.PLAYERS, 1f, 0.8f);
        if (e.getHitEntity() instanceof LivingEntity target && !(target instanceof Player pl && pl.getGameMode() == GameMode.SPECTATOR))
            trap(target);
    }

    // ---------------------------------------------------------------- the trap

    private void trap(LivingEntity target) {
        var cfg = plugin.getConfig();
        UUID id = target.getUniqueId();
        Trap trap = trapped.get(id);
        int until = Bukkit.getCurrentTick() + Math.max(1, cfg.getInt("goo.trap-ticks", 70));
        if (trap != null) { trap.until = until; trap.presses = 0; return; }   // hit again: start over
        trap = new Trap();
        trap.until = until;
        trapped.put(id, trap);

        // can't walk, jump or fall (transient modifiers, so never saved with the entity)
        for (Attribute a : new Attribute[]{Attribute.MOVEMENT_SPEED, Attribute.JUMP_STRENGTH, Attribute.FLYING_SPEED, Attribute.GRAVITY}) {
            AttributeInstance inst = target.getAttribute(a);
            if (inst != null && inst.getModifier(trapKey) == null)
                inst.addTransientModifier(new AttributeModifier(trapKey, -1, AttributeModifier.Operation.MULTIPLY_SCALAR_1, EquipmentSlotGroup.ANY));
        }
        target.setVelocity(new Vector(0, 0, 0));
        if (target instanceof Mob mob && mob.isAware()) { mob.setAware(false); madeUnaware.add(id); }

        // a honey-block shell round the target, a bit bigger than its hitbox
        float wdt = (float) Math.max(0.9, target.getWidth() + 0.3), hgt = (float) (target.getHeight() + 0.3);
        Location base = target.getLocation();
        trap.shell = target.getWorld().spawn(base, BlockDisplay.class, d -> {
            d.setBlock(Material.HONEY_BLOCK.createBlockData());
            d.setTransformation(new Transformation(new Vector3f(-wdt / 2, -0.1f, -wdt / 2), new AxisAngle4f(),
                    new Vector3f(wdt, hgt, wdt), new AxisAngle4f()));
            d.setPersistent(false);   // never saved: a restart can't leave a stray shell behind
        });
        target.getWorld().playSound(base, Sound.BLOCK_HONEY_BLOCK_SLIDE, SoundCategory.PLAYERS, 1.2f, 0.6f);
        if (target instanceof Player pl) showProgress(pl, trap);

        Trap t = trap;
        new BukkitRunnable() {
            @Override public void run() {
                if (trapped.get(id) != t) { cancel(); return; }
                if (!target.isValid() || Bukkit.getCurrentTick() >= t.until) { release(target, false); cancel(); return; }
                if (!(target instanceof Player)) target.setVelocity(new Vector(0, 0, 0));
                if (t.shell != null && t.shell.isValid()) t.shell.teleport(target.getLocation());   // stays wrapped round it
            }
        }.runTaskTimer(plugin, 1, 1);
    }

    private void release(LivingEntity target, boolean brokeFree) {
        UUID id = target.getUniqueId();
        Trap trap = trapped.remove(id);
        if (trap == null) return;
        if (trap.shell != null) trap.shell.remove();
        for (Attribute a : new Attribute[]{Attribute.MOVEMENT_SPEED, Attribute.JUMP_STRENGTH, Attribute.FLYING_SPEED, Attribute.GRAVITY}) {
            AttributeInstance inst = target.getAttribute(a);
            if (inst != null) inst.removeModifier(trapKey);
        }
        if (madeUnaware.remove(id) && target instanceof Mob mob) mob.setAware(true);
        if (!target.isValid()) return;
        Location at = target.getLocation().add(0, target.getHeight() / 2, 0);
        target.getWorld().spawnParticle(Particle.BLOCK, at, 40, 0.4, 0.6, 0.4, 0, Material.HONEY_BLOCK.createBlockData());
        target.getWorld().playSound(at, Sound.BLOCK_HONEY_BLOCK_BREAK, SoundCategory.PLAYERS, 1.2f, brokeFree ? 1.2f : 0.9f);
        if (target instanceof Player pl)
            pl.sendActionBar(Component.text(brokeFree ? "You broke free!" : "The goo dissolves", NamedTextColor.GOLD));
    }

    // ---------------------------------------------------------------- breaking free

    @EventHandler
    public void onSneak(PlayerToggleSneakEvent e) {
        if (!e.isSneaking()) return;   // count presses, not releases
        Player p = e.getPlayer();
        Trap trap = trapped.get(p.getUniqueId());
        if (trap == null) return;
        trap.presses++;
        p.getWorld().playSound(p.getLocation(), Sound.BLOCK_HONEY_BLOCK_STEP, SoundCategory.PLAYERS, 1f, 0.8f + trap.presses * 0.05f);
        p.getWorld().spawnParticle(Particle.BLOCK, p.getLocation().add(0, 1, 0), 6, 0.3, 0.5, 0.3, 0, Material.HONEY_BLOCK.createBlockData());
        if (trap.presses >= needed()) release(p, true);
        else showProgress(p, trap);
    }

    private int needed() { return Math.max(1, plugin.getConfig().getInt("goo.break-free-presses", 12)); }

    private void showProgress(Player p, Trap trap) {
        int need = needed(), done = Math.min(trap.presses, need);
        p.sendActionBar(Component.text("Mash SHIFT to break free! ", NamedTextColor.GOLD)
                .append(Component.text("■".repeat(done), NamedTextColor.YELLOW))
                .append(Component.text("■".repeat(need - done), NamedTextColor.DARK_GRAY)));
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent e) { release(e.getPlayer(), false); }

    /** Called when the plugin shuts down: nobody stays stuck. */
    void releaseAll() {
        for (UUID id : Set.copyOf(trapped.keySet())) {
            Entity ent = Bukkit.getEntity(id);
            if (ent instanceof LivingEntity le) release(le, false);
            else { Trap t = trapped.remove(id); if (t != null && t.shell != null) t.shell.remove(); }
        }
    }
}
