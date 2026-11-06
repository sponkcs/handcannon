package dev.handcannon;

import net.kyori.adventure.resource.ResourcePackInfo;
import net.kyori.adventure.resource.ResourcePackRequest;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.format.NamedTextColor;
import net.kyori.adventure.text.format.TextDecoration;
import org.bukkit.Bukkit;
import org.bukkit.FluidCollisionMode;
import org.bukkit.GameMode;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.NamespacedKey;
import org.bukkit.Particle;
import org.bukkit.Sound;
import org.bukkit.SoundCategory;
import org.bukkit.World;
import org.bukkit.block.Block;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.command.TabExecutor;
import org.bukkit.entity.Entity;
import org.bukkit.entity.LivingEntity;
import org.bukkit.entity.Player;
import org.bukkit.event.Event;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.block.Action;
import org.bukkit.event.player.PlayerInteractEntityEvent;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.inventory.EquipmentSlot;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.persistence.PersistentDataType;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.util.RayTraceResult;
import org.bukkit.util.Vector;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

public final class HandCannonPlugin extends JavaPlugin implements Listener, TabExecutor {
    private NamespacedKey gunKey;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        gunKey = new NamespacedKey(this, "hand_cannon");
        getServer().getPluginManager().registerEvents(this, this);
        var cmd = getCommand("handcannon");
        if (cmd != null) { cmd.setExecutor(this); cmd.setTabCompleter(this); }
    }

    // ---------------------------------------------------------------- item

    ItemStack createGun() {
        ItemStack it = new ItemStack(Material.CARROT_ON_A_STICK);   // right-click on air always reaches the server
        ItemMeta m = it.getItemMeta();
        m.displayName(Component.text("Hand Cannon", NamedTextColor.GOLD).decoration(TextDecoration.ITALIC, false));
        m.lore(List.of(Component.text("Right-click to fire", NamedTextColor.GRAY).decoration(TextDecoration.ITALIC, false)));
        m.setItemModel(NamespacedKey.fromString("handcannon:hand_cannon"));
        m.getPersistentDataContainer().set(gunKey, PersistentDataType.BYTE, (byte) 1);
        it.setItemMeta(m);
        return it;
    }

    boolean isGun(ItemStack it) {
        return it != null && it.hasItemMeta() && it.getItemMeta().getPersistentDataContainer().has(gunKey, PersistentDataType.BYTE);
    }

    // ---------------------------------------------------------------- triggers

    @EventHandler(ignoreCancelled = false)
    public void onInteract(PlayerInteractEvent e) {
        if (e.getAction() != Action.RIGHT_CLICK_AIR && e.getAction() != Action.RIGHT_CLICK_BLOCK) return;
        if (!isGun(e.getItem())) return;
        e.setUseItemInHand(Event.Result.DENY);
        e.setUseInteractedBlock(Event.Result.DENY);
        Player p = e.getPlayer();
        if (e.getHand() == EquipmentSlot.OFF_HAND && isGun(p.getInventory().getItemInMainHand())) return;
        fire(p, e.getItem());
    }

    @EventHandler
    public void onInteractEntity(PlayerInteractEntityEvent e) {   // point-blank: clicking a mob does not raise PlayerInteractEvent
        Player p = e.getPlayer();
        ItemStack it = p.getInventory().getItem(e.getHand());
        if (!isGun(it)) return;
        e.setCancelled(true);
        if (e.getHand() == EquipmentSlot.OFF_HAND && isGun(p.getInventory().getItemInMainHand())) return;
        fire(p, it);
    }

    @EventHandler
    public void onJoin(PlayerJoinEvent e) { sendPack(e.getPlayer()); }

    // ---------------------------------------------------------------- shooting

    private void fire(Player p, ItemStack gun) {
        if (!p.hasPermission("handcannon.use") || p.hasCooldown(gun)) return;
        var cfg = getConfig();
        p.setCooldown(gun, Math.max(1, cfg.getInt("cooldown-ticks", 14)));

        World w = p.getWorld();
        Location eye = p.getEyeLocation();
        Vector dir = eye.getDirection().normalize();
        double range = cfg.getDouble("range", 64);
        RayTraceResult hit = w.rayTrace(eye, dir, range, FluidCollisionMode.NEVER, true, 0.3, ent -> canHit(p, ent));
        Vector end = hit != null ? hit.getHitPosition() : eye.toVector().add(dir.clone().multiply(range));

        // muzzle: in front of the shooter, a little right and down, where the barrel sits on screen
        Vector right = dir.clone().crossProduct(new Vector(0, 1, 0));
        if (right.lengthSquared() < 1e-6) right = new Vector(1, 0, 0); else right.normalize();
        Location muzzle = eye.clone().add(dir.clone().multiply(1.1)).add(right.multiply(0.35)).add(0, -0.25, 0);
        w.spawnParticle(Particle.EXPLOSION, muzzle, 1, 0, 0, 0, 0);
        w.spawnParticle(Particle.FLAME, muzzle, 8, 0.08, 0.08, 0.08, 0.04);
        w.spawnParticle(Particle.LARGE_SMOKE, muzzle, 10, 0.12, 0.12, 0.12, 0.03);
        w.playSound(muzzle, Sound.ENTITY_GENERIC_EXPLODE, SoundCategory.PLAYERS, 1.3f, 1.6f);
        w.playSound(muzzle, Sound.ENTITY_FIREWORK_ROCKET_LARGE_BLAST, SoundCategory.PLAYERS, 1.6f, 0.6f);

        // smoke trail from the muzzle to whatever was hit
        Vector from = muzzle.toVector(), path = end.clone().subtract(from);
        double len = path.length();
        if (len > 0.01) {
            path.multiply(1 / len);
            for (double d = 0.6; d < len; d += 0.5)
                w.spawnParticle(Particle.SMOKE, from.clone().add(path.clone().multiply(d)).toLocation(w), 1, 0, 0, 0, 0);
        }

        Location at = end.toLocation(w);
        if (hit != null && hit.getHitEntity() instanceof LivingEntity target) {
            double dmg = cfg.getDouble("damage", 16);
            boolean head = end.getY() >= target.getEyeLocation().getY() - 0.25;
            if (head) {
                dmg *= cfg.getDouble("headshot-multiplier", 1.5);
                p.playSound(p, Sound.ENTITY_ARROW_HIT_PLAYER, SoundCategory.PLAYERS, 1f, 1.4f);
            }
            target.setNoDamageTicks(0);
            target.damage(dmg, p);
            double kb = cfg.getDouble("knockback", 1.2);
            if (kb > 0) {
                Vector push = dir.clone().setY(0);
                if (push.lengthSquared() > 1e-6) target.setVelocity(target.getVelocity().add(push.normalize().multiply(kb).setY(0.35)));
            }
            w.spawnParticle(Particle.CRIT, at, 20, 0.2, 0.2, 0.2, 0.3);
            w.spawnParticle(Particle.DAMAGE_INDICATOR, at, 6, 0.2, 0.2, 0.2, 0.1);
        } else if (hit != null && hit.getHitBlock() != null) {
            Block b = hit.getHitBlock();
            w.spawnParticle(Particle.BLOCK, at, 24, 0.1, 0.1, 0.1, 0, b.getBlockData());
            w.spawnParticle(Particle.LARGE_SMOKE, at, 4, 0.05, 0.05, 0.05, 0.02);
            w.playSound(at, Sound.BLOCK_DECORATED_POT_SHATTER, SoundCategory.PLAYERS, 0.7f, 1.4f);
        }

        // recoil: the gun is huge, so it shoves the shooter back and kicks the view up
        double recoil = cfg.getDouble("recoil", 0.45);
        if (recoil > 0) {
            Vector back = dir.clone().multiply(-recoil);
            back.setY(back.getY() * 0.5 + 0.08);
            p.setVelocity(p.getVelocity().add(back));
        }
        float kick = (float) cfg.getDouble("pitch-kick", 6);
        if (kick > 0) p.setRotation(p.getYaw(), Math.max(-90f, p.getPitch() - kick));
    }

    private static boolean canHit(Player shooter, Entity ent) {
        if (ent == shooter || !(ent instanceof LivingEntity le) || le.isDead()) return false;
        return !(ent instanceof Player pl && pl.getGameMode() == GameMode.SPECTATOR);
    }

    // ---------------------------------------------------------------- resource pack

    void sendPack(Player p) {
        String url = getConfig().getString("resource-pack.url", "").trim();
        String sha1 = getConfig().getString("resource-pack.sha1", "").trim();
        if (url.isBlank() || sha1.length() != 40) return;
        try {
            ResourcePackInfo info = ResourcePackInfo.resourcePackInfo()
                    .id(UUID.nameUUIDFromBytes("handcannon-pack".getBytes(StandardCharsets.UTF_8)))
                    .uri(URI.create(url)).hash(sha1).build();
            p.sendResourcePacks(ResourcePackRequest.resourcePackRequest().packs(info)
                    .prompt(Component.text("Hand Cannon model"))
                    .required(getConfig().getBoolean("resource-pack.required", false)).build());
        } catch (IllegalArgumentException ex) {
            getLogger().warning("Bad resource-pack settings in config.yml: " + ex.getMessage());
        }
    }

    // ---------------------------------------------------------------- command

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        String sub = args.length == 0 ? "give" : args[0].toLowerCase();
        switch (sub) {
            case "give" -> {
                Player target;
                if (args.length >= 2) target = Bukkit.getPlayerExact(args[1]);
                else target = sender instanceof Player self ? self : null;
                if (target == null) { sender.sendMessage(Component.text("Usage: /" + label + " give <player>", NamedTextColor.RED)); return true; }
                target.getInventory().addItem(createGun()).values().forEach(left -> target.getWorld().dropItem(target.getLocation(), left));
                sender.sendMessage(Component.text("Gave a Hand Cannon to " + target.getName(), NamedTextColor.GOLD));
            }
            case "reload" -> {
                reloadConfig();
                sender.sendMessage(Component.text("HandCannon config reloaded", NamedTextColor.GOLD));
            }
            case "pack" -> {
                Player target = args.length >= 2 ? Bukkit.getPlayerExact(args[1]) : sender instanceof Player self ? self : null;
                if (target == null) { sender.sendMessage(Component.text("Usage: /" + label + " pack <player>", NamedTextColor.RED)); return true; }
                sendPack(target);
            }
            default -> sender.sendMessage(Component.text("Usage: /" + label + " [give|reload|pack] [player]", NamedTextColor.RED));
        }
        return true;
    }

    @Override
    public List<String> onTabComplete(CommandSender sender, Command command, String alias, String[] args) {
        List<String> out = new ArrayList<>();
        if (args.length == 1) {
            for (String s : List.of("give", "reload", "pack")) if (s.startsWith(args[0].toLowerCase())) out.add(s);
        } else if (args.length == 2 && !args[0].equalsIgnoreCase("reload")) {
            for (Player pl : Bukkit.getOnlinePlayers()) if (pl.getName().toLowerCase().startsWith(args[1].toLowerCase())) out.add(pl.getName());
        }
        return out;
    }
}
