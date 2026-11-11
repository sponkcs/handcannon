package dev.handcannon;

import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.format.NamedTextColor;
import net.kyori.adventure.text.format.TextDecoration;
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
import org.bukkit.inventory.EquipmentSlot;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.persistence.PersistentDataType;
import org.bukkit.util.Vector;

import java.util.List;

/**
 * The Stun Grenade: right-click throws it. It tumbles and rolls, and after a short fuse it pops with a bang, a small
 * puff of smoke and a brief flash of light. For now that's all it does.
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
        m.lore(List.of(Component.text("Right-click to throw", NamedTextColor.GRAY).decoration(TextDecoration.ITALIC, false)));
        m.setItemModel(NamespacedKey.fromString("handcannon:stun_grenade"));
        m.getPersistentDataContainer().set(key, PersistentDataType.BYTE, (byte) 1);
        it.setItemMeta(m);
        return it;
    }

    boolean is(ItemStack it) {
        return it != null && it.hasItemMeta() && it.getItemMeta().getPersistentDataContainer().has(key, PersistentDataType.BYTE);
    }

    @EventHandler
    public void onThrow(PlayerInteractEvent e) {
        if (e.getAction() != Action.RIGHT_CLICK_AIR && e.getAction() != Action.RIGHT_CLICK_BLOCK) return;
        ItemStack held = e.getItem();
        if (!is(held)) return;
        e.setUseItemInHand(Event.Result.DENY);   // not a snowball: we throw it ourselves
        e.setUseInteractedBlock(Event.Result.DENY);
        Player p = e.getPlayer();
        if (e.getHand() == EquipmentSlot.OFF_HAND && is(p.getInventory().getItemInMainHand())) return;
        if (!p.hasPermission("handcannon.use") || p.hasCooldown(held)) return;
        var cfg = plugin.getConfig();
        p.setCooldown(held, Math.max(1, cfg.getInt("grenade.cooldown-ticks", 10)));

        // the thrown grenade is a real item on the ground: it tumbles and rolls, but nothing can pick it up
        ItemStack shown = held.clone();
        shown.setAmount(1);
        ItemMeta sm = shown.getItemMeta();
        sm.getPersistentDataContainer().set(liveKey, PersistentDataType.BYTE, (byte) 1);
        shown.setItemMeta(sm);
        Location eye = p.getEyeLocation();
        Vector vel = eye.getDirection().multiply(cfg.getDouble("grenade.throw-speed", 0.9)).add(new Vector(0, 0.15, 0));
        World w = p.getWorld();
        Item thrown = w.dropItem(eye.clone().add(eye.getDirection().multiply(0.4)), shown, it -> {
            it.setVelocity(vel);
            it.setPickupDelay(Integer.MAX_VALUE);
            it.setCanPlayerPickup(false);
            it.setCanMobPickup(false);
            it.setInvulnerable(true);
            it.setPersistent(false);   // never saved: a restart can't leave a live grenade lying about
        });
        if (p.getGameMode() != GameMode.CREATIVE) held.setAmount(held.getAmount() - 1);
        w.playSound(p.getLocation(), Sound.BLOCK_TRIPWIRE_CLICK_ON, SoundCategory.PLAYERS, 1f, 1.6f);   // pin out
        w.playSound(p.getLocation(), Sound.ENTITY_SNOWBALL_THROW, SoundCategory.PLAYERS, 0.8f, 0.6f);

        int fuse = Math.max(1, cfg.getInt("grenade.fuse-ticks", 30));
        plugin.getServer().getScheduler().runTaskLater(plugin, () -> {
            if (!thrown.isValid()) return;
            Location at = thrown.getLocation().add(0, 0.2, 0);
            thrown.remove();
            pop(at);
        }, fuse);
    }

    private void pop(Location at) {
        World w = at.getWorld();
        w.playSound(at, Sound.ENTITY_FIREWORK_ROCKET_BLAST, SoundCategory.PLAYERS, 2.0f, 1.3f);
        w.playSound(at, Sound.ENTITY_GENERIC_EXPLODE, SoundCategory.PLAYERS, 0.7f, 1.8f);
        w.spawnParticle(Particle.CLOUD, at, 10, 0.25, 0.2, 0.25, 0.03);
        w.spawnParticle(Particle.SMOKE, at, 20, 0.3, 0.2, 0.3, 0.02);
        // the flash: the particle (its data type differs between versions, so ask it what it wants)
        if (Particle.FLASH.getDataType() == Color.class) w.spawnParticle(Particle.FLASH, at, 1, 0, 0, 0, 0, Color.WHITE);
        else if (Particle.FLASH.getDataType() == Void.class) w.spawnParticle(Particle.FLASH, at, 1, 0, 0, 0, 0);
        w.spawnParticle(Particle.END_ROD, at, 12, 0.1, 0.1, 0.1, 0.15);
        // ...and a moment of real light: an invisible light block in the air where it popped, removed again after a few ticks
        Block b = at.getBlock();
        if (b.getType() == Material.AIR || b.getType() == Material.CAVE_AIR) {
            Light light = (Light) Material.LIGHT.createBlockData();
            light.setLevel(15);
            b.setBlockData(light, false);
            plugin.getServer().getScheduler().runTaskLater(plugin, () -> {
                if (b.getType() == Material.LIGHT) b.setType(Material.AIR, false);
            }, Math.max(1, plugin.getConfig().getInt("grenade.flash-ticks", 4)));
        }
    }

    /** Hoppers can't swallow a live grenade. */
    @EventHandler
    public void onHopper(InventoryPickupItemEvent e) {
        ItemStack it = e.getItem().getItemStack();
        if (it.hasItemMeta() && it.getItemMeta().getPersistentDataContainer().has(liveKey, PersistentDataType.BYTE)) e.setCancelled(true);
    }

    /** It's a snowball underneath: keep it out of crafting grids (it would make snow blocks). */
    @EventHandler
    public void onCraft(PrepareItemCraftEvent e) {
        for (ItemStack it : e.getInventory().getMatrix()) if (is(it)) { e.getInventory().setResult(null); return; }
    }
}
