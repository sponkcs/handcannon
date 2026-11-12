package dev.handcannon;

import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.format.NamedTextColor;
import net.kyori.adventure.text.format.TextDecoration;
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
import org.bukkit.block.Block;
import org.bukkit.entity.BlockDisplay;
import org.bukkit.entity.Entity;
import org.bukkit.entity.LivingEntity;
import org.bukkit.entity.Player;
import org.bukkit.entity.Snowball;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.entity.ProjectileHitEvent;
import org.bukkit.event.inventory.PrepareItemCraftEvent;
import org.bukkit.inventory.EquipmentSlotGroup;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.persistence.PersistentDataType;
import org.bukkit.scheduler.BukkitTask;
import org.bukkit.util.Transformation;
import org.joml.AxisAngle4f;
import org.joml.Vector3f;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

/**
 * The Goo Grenade: a flask thrown like a snowball. Where it smashes it leaves a puddle of goo for a few seconds;
 * anything standing in it is slowed right down (and can barely jump) until it wades out. No damage.
 */
final class GooGrenade implements Listener {
    private final HandCannonPlugin plugin;
    private final NamespacedKey key, slowKey;
    private final List<Puddle> puddles = new ArrayList<>();
    /** Entities currently slowed by a puddle. */
    private final Set<UUID> slowed = new HashSet<>();
    private BukkitTask ticker;

    private static final class Puddle {
        Location centre;
        double radius;
        int until;
        final List<BlockDisplay> shown = new ArrayList<>();
    }

    GooGrenade(HandCannonPlugin plugin) {
        this.plugin = plugin;
        key = new NamespacedKey(plugin, "goo_grenade");
        slowKey = new NamespacedKey(plugin, "goo_puddle_slow");
    }

    ItemStack create(int amount) {
        // a snowball underneath, so Minecraft throws it (and uses one up) by itself; it flies as the flask model
        ItemStack it = new ItemStack(Material.SNOWBALL, Math.max(1, Math.min(16, amount)));
        ItemMeta m = it.getItemMeta();
        m.displayName(Component.text("Goo Grenade", NamedTextColor.GOLD).decoration(TextDecoration.ITALIC, false));
        m.lore(List.of(Component.text("Right-click to throw", NamedTextColor.GRAY).decoration(TextDecoration.ITALIC, false)));
        m.setItemModel(NamespacedKey.fromString("handcannon:goo_grenade"));
        m.getPersistentDataContainer().set(key, PersistentDataType.BYTE, (byte) 1);
        it.setItemMeta(m);
        return it;
    }

    boolean is(ItemStack it) {
        return it != null && it.hasItemMeta() && it.getItemMeta().getPersistentDataContainer().has(key, PersistentDataType.BYTE);
    }

    private boolean isFlask(Entity e) { return e instanceof Snowball sb && is(sb.getItem()); }

    /** The flask itself does no damage or knockback. */
    @EventHandler(priority = EventPriority.LOWEST)
    public void onFlaskDamage(EntityDamageByEntityEvent e) {
        if (isFlask(e.getDamager())) e.setCancelled(true);
    }

    @EventHandler
    public void onSmash(ProjectileHitEvent e) {
        if (!isFlask(e.getEntity())) return;
        Location hit = e.getHitEntity() != null ? e.getHitEntity().getLocation() : e.getEntity().getLocation();
        World w = hit.getWorld();
        w.playSound(hit, Sound.BLOCK_GLASS_BREAK, SoundCategory.PLAYERS, 1f, 1.2f);
        w.playSound(hit, Sound.BLOCK_HONEY_BLOCK_BREAK, SoundCategory.PLAYERS, 1f, 0.7f);
        w.spawnParticle(Particle.BLOCK, hit, 20, 0.2, 0.2, 0.2, 0, Material.GLASS.createBlockData());
        w.spawnParticle(Particle.BLOCK, hit, 30, 0.3, 0.3, 0.3, 0, Material.HONEY_BLOCK.createBlockData());
        Location ground = findGround(hit);
        if (ground != null) spread(ground);
    }

    /** The top of the first solid block at or below where it smashed (up to 6 blocks down). */
    private static Location findGround(Location at) {
        Block b = at.getBlock();
        for (int i = 0; i <= 6; i++, b = b.getRelative(0, -1, 0)) {
            if (b.getType().isSolid()) return new Location(at.getWorld(), at.getX(), b.getY() + 1, at.getZ());
        }
        return null;
    }

    private void spread(Location centre) {
        var cfg = plugin.getConfig();
        Puddle pd = new Puddle();
        pd.centre = centre;
        pd.radius = Math.max(0.5, cfg.getDouble("goo-grenade.radius", 3.0));
        pd.until = Bukkit.getCurrentTick() + Math.max(1, cfg.getInt("goo-grenade.duration-ticks", 160));
        // the puddle: two thin honey slabs, one turned 45 degrees, so it reads as a rough circle
        float side = (float) (pd.radius * 1.8);
        for (float deg : new float[]{0f, 45f}) {
            var q = new org.joml.Quaternionf().rotateY((float) Math.toRadians(deg));
            Vector3f middle = new Vector3f(side / 2, 0, side / 2).rotate(q);
            pd.shown.add(centre.getWorld().spawn(centre.clone().add(0, deg == 0 ? 0.01 : 0.02, 0), BlockDisplay.class, d -> {
                d.setBlock(Material.HONEY_BLOCK.createBlockData());
                d.setTransformation(new Transformation(new Vector3f(-middle.x, 0, -middle.z), q,
                        new Vector3f(side, 0.06f, side), new org.joml.Quaternionf()));
                d.setPersistent(false);   // never saved: a restart can't leave a stray puddle behind
            }));
        }
        puddles.add(pd);
        if (ticker == null) ticker = Bukkit.getScheduler().runTaskTimer(plugin, this::tick, 1, 2);
    }

    /** Every other tick: slow whatever's standing in goo, free whatever has waded out, and clear old puddles. */
    private void tick() {
        int now = Bukkit.getCurrentTick();
        for (var it = puddles.iterator(); it.hasNext(); ) {
            Puddle pd = it.next();
            if (now >= pd.until) {
                pd.shown.forEach(Entity::remove);
                World w = pd.centre.getWorld();
                w.spawnParticle(Particle.BLOCK, pd.centre, 20, pd.radius / 2, 0.05, pd.radius / 2, 0, Material.HONEY_BLOCK.createBlockData());
                it.remove();
            } else if (now % 10 == 0) {
                pd.centre.getWorld().spawnParticle(Particle.DRIPPING_HONEY, pd.centre.clone().add(0, 0.1, 0), 4,
                        pd.radius / 2, 0, pd.radius / 2, 0);
            }
        }
        Set<UUID> inside = new HashSet<>();
        for (Puddle pd : puddles) {
            for (Entity ent : pd.centre.getWorld().getNearbyEntities(pd.centre, pd.radius, 1.5, pd.radius)) {
                if (!(ent instanceof LivingEntity le) || le.isDead()) continue;
                if (le instanceof Player pl && (pl.getGameMode() == GameMode.SPECTATOR || pl.isFlying())) continue;
                double dx = le.getX() - pd.centre.getX(), dz = le.getZ() - pd.centre.getZ();
                double dy = le.getY() - pd.centre.getY();
                if (dx * dx + dz * dz <= pd.radius * pd.radius && dy > -0.6 && dy < 0.6) inside.add(le.getUniqueId());
            }
        }
        for (UUID id : inside) {
            if (slowed.add(id) && Bukkit.getEntity(id) instanceof LivingEntity le) {
                setSlow(le, true);
                if (le instanceof Player pl) pl.sendActionBar(Component.text("Stuck in goo! Wade out slowly", NamedTextColor.GOLD));
                le.getWorld().playSound(le.getLocation(), Sound.BLOCK_HONEY_BLOCK_SLIDE, SoundCategory.PLAYERS, 1f, 0.7f);
            }
        }
        for (var it = slowed.iterator(); it.hasNext(); ) {
            UUID id = it.next();
            if (inside.contains(id)) continue;
            it.remove();
            if (Bukkit.getEntity(id) instanceof LivingEntity le) setSlow(le, false);
        }
        if (puddles.isEmpty() && slowed.isEmpty() && ticker != null) { ticker.cancel(); ticker = null; }
    }

    private void setSlow(LivingEntity le, boolean on) {
        var cfg = plugin.getConfig();
        double speedCut = Math.min(0.99, Math.max(0, cfg.getDouble("goo-grenade.slow", 0.75)));
        double jumpCut = Math.min(0.99, Math.max(0, cfg.getDouble("goo-grenade.jump-cut", 0.6)));
        for (var pair : new Object[][]{{Attribute.MOVEMENT_SPEED, speedCut}, {Attribute.JUMP_STRENGTH, jumpCut}}) {
            AttributeInstance inst = le.getAttribute((Attribute) pair[0]);
            if (inst == null) continue;
            inst.removeModifier(slowKey);
            if (on) inst.addTransientModifier(new AttributeModifier(slowKey, -(double) pair[1],
                    AttributeModifier.Operation.MULTIPLY_SCALAR_1, EquipmentSlotGroup.ANY));
        }
    }

    /** It's a snowball underneath: keep it out of crafting grids (it would make snow blocks). */
    @EventHandler
    public void onCraft(PrepareItemCraftEvent e) {
        for (ItemStack it : e.getInventory().getMatrix()) if (is(it)) { e.getInventory().setResult(null); return; }
    }

    /** Called when the plugin shuts down: puddles go and nobody stays slowed. */
    void clearAll() {
        for (Puddle pd : puddles) pd.shown.forEach(Entity::remove);
        puddles.clear();
        for (UUID id : slowed) if (Bukkit.getEntity(id) instanceof LivingEntity le) setSlow(le, false);
        slowed.clear();
        if (ticker != null) { ticker.cancel(); ticker = null; }
    }
}
