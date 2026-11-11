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
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.configuration.file.FileConfiguration;
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
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;
import java.util.List;
import java.util.UUID;

public final class HandCannonPlugin extends JavaPlugin implements Listener, TabExecutor {
    private NamespacedKey gunKey, tommyKey, shotgunKey;
    private NailBat bat;
    private PalaPistol pala;
    private GooCannon goo;
    private UmbralLance umbral;
    private RadiantAnkh ankh;
    private StunGrenade grenade;
    /** Last tick each player fired the Tommy gun, so one click can't fire twice (both hands, block + entity events). */
    private final Map<UUID, Integer> lastTommyShot = new HashMap<>();

    @Override
    public void onEnable() {
        saveDefaultConfig();
        getConfig().options().copyDefaults(true);   // add settings from newer versions to an existing config.yml
        saveConfig();
        gunKey = new NamespacedKey(this, "hand_cannon");
        tommyKey = new NamespacedKey(this, "tommy_gun");
        shotgunKey = new NamespacedKey(this, "shotgun");
        bat = new NailBat(this);
        pala = new PalaPistol(this);
        goo = new GooCannon(this);
        umbral = new UmbralLance(this);
        ankh = new RadiantAnkh(this);
        grenade = new StunGrenade(this);
        getServer().getPluginManager().registerEvents(this, this);
        getServer().getPluginManager().registerEvents(bat, this);
        getServer().getPluginManager().registerEvents(pala, this);
        getServer().getPluginManager().registerEvents(goo, this);
        getServer().getPluginManager().registerEvents(umbral, this);
        getServer().getPluginManager().registerEvents(ankh, this);
        getServer().getPluginManager().registerEvents(grenade, this);
        var cmd = getCommand("handcannon");
        if (cmd != null) { cmd.setExecutor(this); cmd.setTabCompleter(this); }
    }

    @Override
    public void onDisable() {
        if (pala != null) pala.releaseAll();   // nobody stays stunned or stuck across a restart
        if (goo != null) goo.releaseAll();
    }

    // ---------------------------------------------------------------- items

    ItemStack makeGun(NamespacedKey key, String name, String hint, String model) {
        ItemStack it = new ItemStack(Material.CARROT_ON_A_STICK);   // right-click on air always reaches the server
        ItemMeta m = it.getItemMeta();
        m.displayName(Component.text(name, NamedTextColor.GOLD).decoration(TextDecoration.ITALIC, false));
        m.lore(List.of(Component.text(hint, NamedTextColor.GRAY).decoration(TextDecoration.ITALIC, false)));
        m.setItemModel(NamespacedKey.fromString(model));
        m.getPersistentDataContainer().set(key, PersistentDataType.BYTE, (byte) 1);
        it.setItemMeta(m);
        return it;
    }
    ItemStack createGun() { return makeGun(gunKey, "Hand Cannon", "Right-click to fire", "handcannon:hand_cannon"); }
    ItemStack createTommy() { return makeGun(tommyKey, "Tommy Gun", "Hold right-click to fire", "handcannon:tommy_gun"); }
    ItemStack createShotgun() { return makeGun(shotgunKey, "Double Barrel", "Right-click to fire", "handcannon:shotgun"); }

    private static boolean has(ItemStack it, NamespacedKey key) {
        return it != null && it.hasItemMeta() && it.getItemMeta().getPersistentDataContainer().has(key, PersistentDataType.BYTE);
    }
    boolean isGun(ItemStack it) { return has(it, gunKey); }
    boolean isTommy(ItemStack it) { return has(it, tommyKey); }
    boolean isShotgun(ItemStack it) { return has(it, shotgunKey); }
    private boolean isAnyGun(ItemStack it) { return isGun(it) || isTommy(it) || isShotgun(it); }

    // ---------------------------------------------------------------- triggers

    @EventHandler(ignoreCancelled = false)
    public void onInteract(PlayerInteractEvent e) {
        if (e.getAction() != Action.RIGHT_CLICK_AIR && e.getAction() != Action.RIGHT_CLICK_BLOCK) return;
        if (!isAnyGun(e.getItem())) return;
        e.setUseItemInHand(Event.Result.DENY);
        e.setUseInteractedBlock(Event.Result.DENY);
        Player p = e.getPlayer();
        if (e.getHand() == EquipmentSlot.OFF_HAND && isAnyGun(p.getInventory().getItemInMainHand())) return;
        trigger(p, e.getItem());
    }

    @EventHandler
    public void onInteractEntity(PlayerInteractEntityEvent e) {   // point-blank: clicking a mob does not raise PlayerInteractEvent
        Player p = e.getPlayer();
        ItemStack it = p.getInventory().getItem(e.getHand());
        if (!isAnyGun(it)) return;
        e.setCancelled(true);
        if (e.getHand() == EquipmentSlot.OFF_HAND && isAnyGun(p.getInventory().getItemInMainHand())) return;
        trigger(p, it);
    }

    @EventHandler
    public void onJoin(PlayerJoinEvent e) { sendPack(e.getPlayer()); }

    @EventHandler
    public void onQuit(PlayerQuitEvent e) { lastTommyShot.remove(e.getPlayer().getUniqueId()); }

    private void trigger(Player p, ItemStack gun) {
        if (!p.hasPermission("handcannon.use")) return;
        var cfg = getConfig();
        if (isGun(gun) || isShotgun(gun)) {   // one shot per click, then a cooldown (shown as the sweep on the item)
            if (p.hasCooldown(gun)) return;
            boolean shotgun = isShotgun(gun);
            p.setCooldown(gun, Math.max(1, shotgun ? cfg.getInt("shotgun.cooldown-ticks", 20) : cfg.getInt("cooldown-ticks", 14)));
            shoot(p, shotgun ? Stats.shotgun(cfg) : Stats.cannon(cfg));
            return;
        }
        // Tommy gun: holding right-click repeats the click every 4 ticks; each click fires a short burst
        int now = Bukkit.getCurrentTick();
        Integer last = lastTommyShot.get(p.getUniqueId());
        if (last != null && now - last < 3) return;
        lastTommyShot.put(p.getUniqueId(), now);
        Stats st = Stats.tommy(cfg);
        shoot(p, st);
        int extra = Math.max(1, cfg.getInt("tommy.shots-per-click", 2)) - 1;
        for (int i = 1; i <= extra; i++) {
            int delay = i * 4 / (extra + 1);
            Bukkit.getScheduler().runTaskLater(this, () -> {
                if (p.isOnline() && !p.isDead() && isTommy(p.getInventory().getItemInMainHand())) shoot(p, st);
            }, Math.max(1, delay));
        }
    }

    // ---------------------------------------------------------------- shooting

    enum Kind { CANNON, TOMMY, SHOTGUN }

    /** Per-gun numbers, read fresh from config.yml on every shot. */
    record Stats(Kind kind, double damage, double headshot, double range, double spread, int pellets,
                 double knockback, double recoil, float kick) {
        static Stats cannon(FileConfiguration c) {
            return new Stats(Kind.CANNON, c.getDouble("damage", 10), c.getDouble("headshot-multiplier", 1.0), c.getDouble("range", 64), 0, 1,
                    c.getDouble("knockback", 1.2), c.getDouble("recoil", 0.45), (float) c.getDouble("pitch-kick", 6));
        }
        static Stats tommy(FileConfiguration c) {
            // no view kick: turning the player's camera on every bullet fights their mouse and makes aiming stutter
            return new Stats(Kind.TOMMY, c.getDouble("tommy.damage", 10), c.getDouble("tommy.headshot-multiplier", 1.0),
                    c.getDouble("tommy.range", 48), c.getDouble("tommy.spread", 2.5), 1, c.getDouble("tommy.knockback", 0.15),
                    0, 0f);
        }
        static Stats shotgun(FileConfiguration c) {
            return new Stats(Kind.SHOTGUN, c.getDouble("shotgun.damage", 10), c.getDouble("shotgun.headshot-multiplier", 1.0),
                    c.getDouble("shotgun.range", 24), c.getDouble("shotgun.spread", 6), Math.max(1, c.getInt("shotgun.pellets", 8)),
                    c.getDouble("shotgun.knockback", 1.0), c.getDouble("shotgun.recoil", 0.3), (float) c.getDouble("shotgun.pitch-kick", 4));
        }
    }

    private void shoot(Player p, Stats st) {
        World w = p.getWorld();
        Location eye = p.getEyeLocation();
        Vector aim = eye.getDirection().normalize();
        var r = ThreadLocalRandom.current();

        // muzzle: in front of the shooter, a little right and down, where the barrel sits on screen
        Vector right = aim.clone().crossProduct(new Vector(0, 1, 0));
        if (right.lengthSquared() < 1e-6) right = new Vector(1, 0, 0); else right.normalize();
        Location muzzle = eye.clone().add(aim.clone().multiply(st.kind() == Kind.CANNON ? 1.1 : 1.3)).add(right.multiply(0.35)).add(0, -0.25, 0);
        switch (st.kind()) {
            case CANNON -> {
                w.spawnParticle(Particle.EXPLOSION, muzzle, 1, 0, 0, 0, 0);
                w.spawnParticle(Particle.FLAME, muzzle, 8, 0.08, 0.08, 0.08, 0.04);
                w.spawnParticle(Particle.LARGE_SMOKE, muzzle, 10, 0.12, 0.12, 0.12, 0.03);
                w.playSound(muzzle, Sound.ENTITY_GENERIC_EXPLODE, SoundCategory.PLAYERS, 1.3f, 1.6f);
                w.playSound(muzzle, Sound.ENTITY_FIREWORK_ROCKET_LARGE_BLAST, SoundCategory.PLAYERS, 1.6f, 0.6f);
            }
            case TOMMY -> {
                w.spawnParticle(Particle.FLAME, muzzle, 2, 0.04, 0.04, 0.04, 0.02);
                w.spawnParticle(Particle.SMOKE, muzzle, 2, 0.05, 0.05, 0.05, 0.01);
                w.playSound(muzzle, Sound.ENTITY_FIREWORK_ROCKET_BLAST, SoundCategory.PLAYERS, 0.9f, 1.8f);
                w.playSound(muzzle, Sound.ENTITY_GENERIC_EXPLODE, SoundCategory.PLAYERS, 0.2f, 2.0f);
            }
            case SHOTGUN -> {
                w.spawnParticle(Particle.FLAME, muzzle, 10, 0.12, 0.12, 0.12, 0.08);
                w.spawnParticle(Particle.LARGE_SMOKE, muzzle, 14, 0.18, 0.18, 0.18, 0.05);
                w.playSound(muzzle, Sound.ENTITY_GENERIC_EXPLODE, SoundCategory.PLAYERS, 1.1f, 1.2f);
                w.playSound(muzzle, Sound.ENTITY_FIREWORK_ROCKET_LARGE_BLAST, SoundCategory.PLAYERS, 1.4f, 0.8f);
            }
        }

        // trace every pellet (one for the cannon and Tommy gun); a target is damaged once however many pellets hit it
        Map<LivingEntity, Integer> struck = new LinkedHashMap<>();
        Map<LivingEntity, Boolean> headshot = new HashMap<>();
        double trailStep = st.kind() == Kind.CANNON ? 0.5 : st.kind() == Kind.SHOTGUN ? 1.0 : 1.5;
        for (int n = 0; n < st.pellets(); n++) {
            Vector dir = aim.clone();
            if (st.spread() > 0) {   // wobble inside a cone of the given half-angle
                double t = Math.tan(Math.toRadians(st.spread()));
                dir.add(new Vector(r.nextGaussian(), r.nextGaussian(), r.nextGaussian()).multiply(t * 0.5)).normalize();
            }
            RayTraceResult hit = w.rayTrace(eye, dir, st.range(), FluidCollisionMode.NEVER, true, 0.3, ent -> canHit(p, ent));
            Vector end = hit != null ? hit.getHitPosition() : eye.toVector().add(dir.clone().multiply(st.range()));

            Vector from = muzzle.toVector(), path = end.clone().subtract(from);
            double len = path.length();
            if (len > 0.01) {
                path.multiply(1 / len);
                for (double d = 0.6; d < len; d += trailStep)
                    w.spawnParticle(Particle.SMOKE, from.clone().add(path.clone().multiply(d)).toLocation(w), 1, 0, 0, 0, 0);
            }

            Location at = end.toLocation(w);
            if (hit != null && hit.getHitEntity() instanceof LivingEntity target) {
                struck.merge(target, 1, Integer::sum);
                if (end.getY() >= target.getEyeLocation().getY() - 0.25) headshot.put(target, true);
                w.spawnParticle(Particle.CRIT, at, st.kind() == Kind.CANNON ? 20 : 4, 0.2, 0.2, 0.2, 0.3);
            } else if (hit != null && hit.getHitBlock() != null) {
                Block b = hit.getHitBlock();
                w.spawnParticle(Particle.BLOCK, at, st.kind() == Kind.CANNON ? 24 : 6, 0.1, 0.1, 0.1, 0, b.getBlockData());
                if (st.kind() == Kind.CANNON) {
                    w.spawnParticle(Particle.LARGE_SMOKE, at, 4, 0.05, 0.05, 0.05, 0.02);
                    w.playSound(at, Sound.BLOCK_DECORATED_POT_SHATTER, SoundCategory.PLAYERS, 0.7f, 1.4f);
                }
            }
        }

        for (var entry : struck.entrySet()) {
            LivingEntity target = entry.getKey();
            double dmg = st.damage();
            if (headshot.containsKey(target) && st.headshot() != 1.0) {
                dmg *= st.headshot();
                p.playSound(p, Sound.ENTITY_ARROW_HIT_PLAYER, SoundCategory.PLAYERS, st.kind() == Kind.TOMMY ? 0.4f : 1f, 1.4f);
            }
            target.setNoDamageTicks(0);
            target.damage(dmg, p);
            double kb = st.knockback() * entry.getValue() / st.pellets();   // shotgun: the more pellets, the bigger the shove
            if (kb > 0) {
                Vector push = aim.clone().setY(0);
                if (push.lengthSquared() > 1e-6)
                    target.setVelocity(target.getVelocity().add(push.normalize().multiply(kb).setY(st.kind() == Kind.TOMMY ? 0.05 : 0.35)));
            }
            if (st.kind() == Kind.CANNON)
                w.spawnParticle(Particle.DAMAGE_INDICATOR, target.getLocation().add(0, target.getHeight() / 2, 0), 6, 0.2, 0.2, 0.2, 0.1);
        }

        // recoil: shove the shooter back and kick the view up
        if (st.recoil() > 0) {
            Vector back = aim.clone().multiply(-st.recoil());
            back.setY(back.getY() * 0.5 + 0.08);
            p.setVelocity(p.getVelocity().add(back));
        }
        if (st.kick() > 0) p.setRotation(p.getYaw(), Math.max(-90f, p.getPitch() - st.kick()));
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
                // /hc give [gun|tommy|shotgun|pala|goo|corruption|holy|grenade|bat] [player] ("ankh" also works) ("umbral" also works); the item can be left out (gun)
                int i = 1;
                String what = "gun";
                if (args.length > i && List.of("gun", "tommy", "shotgun", "pala", "goo", "corruption", "umbral", "holy", "ankh", "grenade", "bat").contains(args[i].toLowerCase())) what = args[i++].toLowerCase();
                Player target;
                if (args.length > i) target = Bukkit.getPlayerExact(args[i]);
                else target = sender instanceof Player self ? self : null;
                if (target == null) { sender.sendMessage(Component.text("Usage: /" + label + " give [gun|tommy|shotgun|pala|goo|corruption|holy|grenade|bat] <player>", NamedTextColor.RED)); return true; }
                ItemStack item = switch (what) { case "bat" -> bat.create(); case "tommy" -> createTommy(); case "shotgun" -> createShotgun(); case "pala" -> pala.create(); case "goo" -> goo.create(); case "corruption", "umbral" -> umbral.create(); case "holy", "ankh" -> ankh.create(); case "grenade" -> grenade.create(1); default -> createGun(); };
                target.getInventory().addItem(item).values().forEach(left -> target.getWorld().dropItem(target.getLocation(), left));
                sender.sendMessage(Component.text("Gave a " + switch (what) { case "bat" -> "Nail Bat"; case "tommy" -> "Tommy Gun"; case "shotgun" -> "Double Barrel"; case "pala" -> "Pala-Pistol"; case "goo" -> "Goo Cannon"; case "corruption", "umbral" -> "Corruption Cannon"; case "holy", "ankh" -> "Holy Blade"; case "grenade" -> "Stun Grenade"; default -> "Hand Cannon"; } + " to " + target.getName(), NamedTextColor.GOLD));
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
            default -> sender.sendMessage(Component.text("Usage: /" + label + " give [gun|tommy|shotgun|pala|goo|corruption|holy|grenade|bat] [player] | reload | pack [player]", NamedTextColor.RED));
        }
        return true;
    }

    @Override
    public List<String> onTabComplete(CommandSender sender, Command command, String alias, String[] args) {
        List<String> out = new ArrayList<>();
        if (args.length == 1) {
            for (String s : List.of("give", "reload", "pack")) if (s.startsWith(args[0].toLowerCase())) out.add(s);
        } else if (args.length == 2 && args[0].equalsIgnoreCase("give")) {
            for (String s : List.of("gun", "tommy", "shotgun", "pala", "goo", "corruption", "holy", "grenade", "bat")) if (s.startsWith(args[1].toLowerCase())) out.add(s);
            for (Player pl : Bukkit.getOnlinePlayers()) if (pl.getName().toLowerCase().startsWith(args[1].toLowerCase())) out.add(pl.getName());
        } else if (args.length == 3 && args[0].equalsIgnoreCase("give")) {
            for (Player pl : Bukkit.getOnlinePlayers()) if (pl.getName().toLowerCase().startsWith(args[2].toLowerCase())) out.add(pl.getName());
        } else if (args.length == 2 && args[0].equalsIgnoreCase("pack")) {
            for (Player pl : Bukkit.getOnlinePlayers()) if (pl.getName().toLowerCase().startsWith(args[1].toLowerCase())) out.add(pl.getName());
        }
        return out;
    }
}
