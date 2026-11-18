package dev.handcannon;

import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.format.NamedTextColor;
import net.kyori.adventure.text.format.TextDecoration;
import io.papermc.paper.event.player.PrePlayerAttackEntityEvent;
import org.bukkit.Bukkit;
import org.bukkit.Color;
import org.bukkit.GameMode;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.NamespacedKey;
import org.bukkit.Particle;
import org.bukkit.Sound;
import org.bukkit.SoundCategory;
import org.bukkit.World;
import org.bukkit.block.Block;
import org.bukkit.block.data.type.Light;
import org.bukkit.entity.Item;
import org.bukkit.entity.Player;
import org.bukkit.event.Event;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.block.Action;
import org.bukkit.event.inventory.InventoryPickupItemEvent;
import org.bukkit.event.inventory.PrepareItemCraftEvent;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.entity.PlayerDeathEvent;
import org.bukkit.inventory.EquipmentSlot;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.persistence.PersistentDataType;
import org.bukkit.scheduler.BukkitTask;
import org.bukkit.util.Vector;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * The Stun Grenade: a roleplay item. Left-click pulls the pin and starts a 3-second fuse; right-click throws it in an
 * easy underarm lob (no aiming). When the fuse runs out it pops, in the air, on the ground or still in the hand, with a
 * bang, a small puff of smoke and a soft, brief glow. It never affects anyone: no blindness, nausea or screen flash.
 */
final class StunGrenade implements Listener {
    private final HandCannonPlugin plugin;
    private final NamespacedKey key, liveKey;

    StunGrenade(HandCannonPlugin plugin) {
        this.plugin = plugin;
        key = new NamespacedKey(plugin, "stun_grenade");
        liveKey = new NamespacedKey(plugin, "stun_grenade_live");
    }

    ItemStack create(int amount) {
        ItemStack it = new ItemStack(Material.SNOWBALL, Math.max(1, Math.min(16, amount)));   // stacks to 16
        ItemMeta m = it.getItemMeta();
        m.displayName(Component.text("Stun Grenade", NamedTextColor.GOLD).decoration(TextDecoration.ITALIC, false));
        m.lore(List.of(Component.text("Left-click to pull the pin, right-click to throw", NamedTextColor.GRAY).decoration(TextDecoration.ITALIC, false)));
        m.setItemModel(NamespacedKey.fromString("handcannon:stun_grenade"));
        m.getPersistentDataContainer().set(key, PersistentDataType.BYTE, (byte) 1);
        it.setItemMeta(m);
        return it;
    }

    boolean is(ItemStack it) {
        return it != null && it.hasItemMeta() && it.getItemMeta().getPersistentDataContainer().has(key, PersistentDataType.BYTE);
    }

    // ---------------------------------------------------------------- left-click: pull the pin

    /** A grenade whose pin is out: when it pops, and the countdown shown to its holder. */
    private static final class Live { int popAt; BukkitTask countdown; BukkitTask inHand; }
    private final Map<UUID, Live> pinned = new HashMap<>();
    /** Last tick each player right-clicked, so the arm swing that follows a right-click isn't taken as a left-click. */
    private final Map<UUID, Integer> lastRightClick = new HashMap<>();

    @EventHandler
    public void onLeftClick(PlayerInteractEvent e) {
        if (e.getAction() != Action.LEFT_CLICK_AIR && e.getAction() != Action.LEFT_CLICK_BLOCK) return;
        if (e.getHand() != EquipmentSlot.HAND || !is(e.getItem())) return;
        e.setCancelled(true);   // don't start breaking the block
        Player p = e.getPlayer();
        Integer rc = lastRightClick.get(p.getUniqueId());
        if (rc != null && Bukkit.getCurrentTick() - rc < 3) return;
        pullPin(p);
    }

    @EventHandler
    public void onLeftClickEntity(PrePlayerAttackEntityEvent e) {   // pulling the pin while looking at a mob or player
        if (!is(e.getPlayer().getInventory().getItemInMainHand())) return;
        e.setCancelled(true);
        pullPin(e.getPlayer());
    }

    private void pullPin(Player p) {
        if (!p.hasPermission("handcannon.use") || pinned.containsKey(p.getUniqueId())) return;
        int fuse = Math.max(1, plugin.getConfig().getInt("grenade.pin-fuse-ticks", 60));
        Live live = new Live();
        live.popAt = Bukkit.getCurrentTick() + fuse;
        pinned.put(p.getUniqueId(), live);
        World w = p.getWorld();
        w.playSound(p.getLocation(), Sound.BLOCK_TRIPWIRE_CLICK_ON, SoundCategory.PLAYERS, 1f, 1.6f);
        w.playSound(p.getLocation(), Sound.BLOCK_CHAIN_PLACE, SoundCategory.PLAYERS, 0.6f, 1.8f);
        w.spawnParticle(Particle.CRIT, handSpot(p), 4, 0.05, 0.05, 0.05, 0.05);
        live.countdown = Bukkit.getScheduler().runTaskTimer(plugin, () -> {
            double left = Math.max(0, (live.popAt - Bukkit.getCurrentTick()) / 20.0);
            p.sendActionBar(Component.text(String.format("Pin pulled! Right-click to throw  %.1f s", left), NamedTextColor.GOLD));
        }, 0, 2);
        // not thrown in time: it pops in the hand (harmless, like every pop)
        live.inHand = Bukkit.getScheduler().runTaskLater(plugin, () -> {
            if (pinned.remove(p.getUniqueId()) != live) return;
            live.countdown.cancel();
            if (!p.isOnline()) return;
            useOne(p);
            pop(handSpot(p));
            p.sendActionBar(Component.text("It went off in your hand", NamedTextColor.GOLD));
        }, fuse);
    }

    private static Location handSpot(Player p) {
        Location eye = p.getEyeLocation();
        return eye.clone().add(eye.getDirection().multiply(0.5)).add(0, -0.4, 0);
    }

    /** Use up one grenade: from the main hand if it's there, otherwise the first one in the inventory. Creative: none. */
    private void useOne(Player p) {
        if (p.getGameMode() == GameMode.CREATIVE) return;
        ItemStack main = p.getInventory().getItemInMainHand();
        if (is(main)) { main.setAmount(main.getAmount() - 1); return; }
        for (ItemStack it : p.getInventory().getContents())
            if (is(it)) { it.setAmount(it.getAmount() - 1); return; }
    }

    // ---------------------------------------------------------------- right-click: throw

    @EventHandler
    public void onThrow(PlayerInteractEvent e) {
        if (e.getAction() != Action.RIGHT_CLICK_AIR && e.getAction() != Action.RIGHT_CLICK_BLOCK) return;
        ItemStack held = e.getItem();
        if (!is(held)) return;
        e.setUseItemInHand(Event.Result.DENY);   // not a snowball: we throw it ourselves
        e.setUseInteractedBlock(Event.Result.DENY);
        Player p = e.getPlayer();
        lastRightClick.put(p.getUniqueId(), Bukkit.getCurrentTick());
        if (e.getHand() == EquipmentSlot.OFF_HAND && is(p.getInventory().getItemInMainHand())) return;
        Live live = pinned.get(p.getUniqueId());
        if (live == null) {
            p.sendActionBar(Component.text("Left-click to pull the pin", NamedTextColor.GRAY));
            return;
        }
        pinned.remove(p.getUniqueId());
        live.countdown.cancel();
        live.inHand.cancel();
        p.sendActionBar(Component.empty());

        // no aiming: always the same easy underarm lob, straight ahead in the direction the player faces
        var cfg = plugin.getConfig();
        Vector ahead = p.getLocation().getDirection().setY(0);
        if (ahead.lengthSquared() < 1e-6) ahead = new Vector(0, 0, 1);
        Vector vel = ahead.normalize().multiply(cfg.getDouble("grenade.lob-forward", 0.6)).setY(cfg.getDouble("grenade.lob-up", 0.35));

        // the thrown grenade is a real item on the ground: it tumbles and rolls, but nothing can pick it up
        ItemStack shown = held.clone();
        shown.setAmount(1);
        ItemMeta sm = shown.getItemMeta();
        // a different tag on every throw, so two grenades landing together never merge into one item (and one pop)
        sm.getPersistentDataContainer().set(liveKey, PersistentDataType.STRING, UUID.randomUUID().toString());
        shown.setItemMeta(sm);
        World w = p.getWorld();
        Item thrown = w.dropItem(handSpot(p), shown, it -> {
            it.setVelocity(vel);
            it.setPickupDelay(Integer.MAX_VALUE);
            it.setCanPlayerPickup(false);
            it.setCanMobPickup(false);
            it.setInvulnerable(true);
            it.setPersistent(false);   // never saved: a restart can't leave a live grenade lying about
        });
        useOne(p);
        p.swingMainHand();
        w.playSound(p.getLocation(), Sound.ENTITY_SNOWBALL_THROW, SoundCategory.PLAYERS, 0.8f, 0.6f);

        // the fuse keeps running from when the pin came out
        long left = Math.max(1, live.popAt - Bukkit.getCurrentTick());
        Bukkit.getScheduler().runTaskLater(plugin, () -> {
            if (!thrown.isValid()) return;
            Location at = thrown.getLocation().add(0, 0.2, 0);
            thrown.remove();
            pop(at);
        }, left);
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent e) {   // leaving with the pin out: the grenade just goes quiet
        defuse(e.getPlayer());
        lastRightClick.remove(e.getPlayer().getUniqueId());
    }

    @EventHandler
    public void onDeath(PlayerDeathEvent e) { defuse(e.getPlayer()); }   // dying with the pin out: same

    private void defuse(Player p) {
        Live live = pinned.remove(p.getUniqueId());
        if (live != null) { live.countdown.cancel(); live.inHand.cancel(); }
    }

    /** Light blocks still showing a glow, so a shutdown mid-glow can't leave one behind. */
    private final java.util.Set<Block> glowing = new java.util.HashSet<>();

    /** Called when the plugin shuts down. */
    void cleanUp() {
        for (Block b : glowing) if (b.getType() == Material.LIGHT) b.setType(Material.AIR, false);
        glowing.clear();
        for (Live live : pinned.values()) { live.countdown.cancel(); live.inHand.cancel(); }
        pinned.clear();
    }

    /**
     * The pop. Purely cosmetic and kept gentle on purpose (it's a roleplay item): no blindness, nausea or other effect
     * on anyone, no full-screen flash, and a moderate bang. A big burst of sparkles and smoke, then several more
     * flurries of light and twinkling crackles around the spot over about a second and a half, while the area glows
     * and then fades back to normal.
     */
    private void pop(Location at) {
        World w = at.getWorld();
        var cfg = plugin.getConfig();
        int length = Math.max(10, cfg.getInt("grenade.sparkle-ticks", 30));
        w.playSound(at, Sound.ENTITY_FIREWORK_ROCKET_BLAST, SoundCategory.PLAYERS, 1.0f, 1.2f);
        w.playSound(at, Sound.ENTITY_GENERIC_EXPLODE, SoundCategory.PLAYERS, 0.3f, 1.8f);
        // the main burst
        w.spawnParticle(Particle.CLOUD, at, 24, 0.5, 0.35, 0.5, 0.05);
        w.spawnParticle(Particle.SMOKE, at, 30, 0.6, 0.3, 0.6, 0.03);
        w.spawnParticle(Particle.FIREWORK, at, 40, 0.15, 0.15, 0.15, 0.18);
        w.spawnParticle(Particle.END_ROD, at, 24, 0.2, 0.2, 0.2, 0.14);
        w.spawnParticle(Particle.DUST, at, 40, 0.8, 0.6, 0.8, 0, WARM);
        // then flurries: little bursts of sparkle and light around the spot, each with a twinkling crackle
        var r = java.util.concurrent.ThreadLocalRandom.current();
        int flurries = 5;
        for (int i = 1; i <= flurries; i++) {
            int when = i * length / (flurries + 1);
            double spread = 0.6 + i * 0.25;
            int count = Math.max(6, 22 - i * 3);
            plugin.getServer().getScheduler().runTaskLater(plugin, () -> {
                for (int burst = 0; burst < 2; burst++) {
                    Location spot = at.clone().add(r.nextDouble(-spread, spread), r.nextDouble(0, spread), r.nextDouble(-spread, spread));
                    w.spawnParticle(Particle.FIREWORK, spot, count, 0.1, 0.1, 0.1, 0.08);
                    w.spawnParticle(Particle.END_ROD, spot, count / 2, 0.15, 0.15, 0.15, 0.05);
                    w.spawnParticle(Particle.DUST, spot, count, 0.3, 0.3, 0.3, 0, WARM);
                }
                w.spawnParticle(Particle.SMOKE, at, 6, spread / 2, 0.2, spread / 2, 0.01);
                w.playSound(at, Sound.ENTITY_FIREWORK_ROCKET_TWINKLE, SoundCategory.PLAYERS, 0.7f, 1.0f + r.nextFloat() * 0.6f);
            }, when);
        }
        // the area glows for the whole effect, then fades: an invisible light block that dims step by step
        Block b = at.getBlock();
        if (b.getType() != Material.AIR && b.getType() != Material.CAVE_AIR) return;
        int[] levels = {14, 13, 12, 12, 11, 10, 9, 8, 6, 4, 2};
        for (int i = 0; i < levels.length; i++) {
            int level = levels[i];
            plugin.getServer().getScheduler().runTaskLater(plugin, () -> {
                if (b.getType() != Material.AIR && b.getType() != Material.CAVE_AIR && b.getType() != Material.LIGHT) return;
                Light light = (Light) Material.LIGHT.createBlockData();
                light.setLevel(level);
                b.setBlockData(light, false);
                glowing.add(b);
            }, (long) i * length / levels.length);
        }
        plugin.getServer().getScheduler().runTaskLater(plugin, () -> {
            if (b.getType() == Material.LIGHT) b.setType(Material.AIR, false);
            glowing.remove(b);
        }, length + 2);
    }

    private static final Particle.DustOptions WARM = new Particle.DustOptions(Color.fromRGB(255, 236, 170), 1.2f);

    /** Hoppers can't swallow a live grenade. */
    @EventHandler
    public void onHopper(InventoryPickupItemEvent e) {
        ItemStack it = e.getItem().getItemStack();
        if (it.hasItemMeta() && it.getItemMeta().getPersistentDataContainer().has(liveKey)) e.setCancelled(true);
    }

    /** It's a snowball underneath: keep it out of crafting grids (it would make snow blocks). */
    @EventHandler
    public void onCraft(PrepareItemCraftEvent e) {
        for (ItemStack it : e.getInventory().getMatrix()) if (is(it)) { e.getInventory().setResult(null); return; }
    }
}
