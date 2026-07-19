--- a/drivers/net/ethernet/marvell/mvmdio.c.orig
+++ a/drivers/net/ethernet/marvell/mvmdio.c
@@ -279,6 +279,65 @@
 	return 0;
 }
 
+static void orion_mdio_shutdown(struct platform_device *pdev)
+{
+	struct mii_bus *bus = platform_get_drvdata(pdev);
+	u16 rega, regb;
+	int i;
+
+	/* replaces /proc/power_mode_2 */
+	/* Force 10Mbps half duplex, disable autoneg */
+	for (i = 0; i < 2; i++) {
+		orion_mdio_write(bus, i, 0x16, 0x0);
+		orion_mdio_write(bus, i, 0x0, 0x8000);
+	}
+	if (system_state == SYSTEM_RESTART) {
+		/* Clear MII_88E1318S_PHY_LED_TCR_INT_ACTIVE_LOW, or the system
+		** will not reboot.  RN2120 appears to rely on a PHY link change
+		** interrupt to "reboot", so make sure it's enabled. */
+		orion_mdio_write(bus, 0, 0x16, 0x3);
+		rega = orion_mdio_read(bus, 0, 0x12);
+		regb = (rega | BIT(7)) & ~(BIT(11));
+	} else {
+		/* WoL enabled? */
+		orion_mdio_write(bus, 0, 0x16, 0x11);
+		rega = orion_mdio_read(bus, 0, 0x10);
+		if (rega & BIT(14)) {
+			/* Enable interrupt only on WOL event.
+			** We get an immediate poweron with large MTU without this */
+			for (i = 0; i < 2; i++) {
+				orion_mdio_write(bus, i, 0x16, 0x0);
+				orion_mdio_write(bus, i, 0x12, 0x80);
+			}
+			/* Magic packet enable, Clear WOL status, ..., 10BT LPM */
+			regb = BIT(14) | BIT(12) | BIT(10) | BIT(8) | BIT(7);
+			pr_debug("MII_88E1318S_PHY_WOL_CTRL: 0x%x => 0x%x\n",
+				rega, regb);
+			for (i = 0; i < 2; i++) {
+				orion_mdio_write(bus, i, 0x16, 0x11);
+				orion_mdio_write(bus, i, 0x10, regb);
+				orion_mdio_write(bus, i, 0x16, 0x3);
+			}
+			rega = orion_mdio_read(bus, 0, 0x12);
+			regb = rega | BIT(11) | BIT(7);
+		} else {
+			for (i = 0; i < 2; i++) {
+				orion_mdio_write(bus, i, 0x16, 0x0);
+				orion_mdio_write(bus, i, 0x0, BMCR_PDOWN);
+				orion_mdio_write(bus, i, 0x12, 0x0);
+				orion_mdio_write(bus, i, 0x16, 0x3);
+			}
+			rega = orion_mdio_read(bus, 0, 0x12);
+			regb = rega & ~(BIT(11) | BIT(7));
+		}
+	}
+	pr_debug("MII_88E1318S_LED_TCR: 0x%x => 0x%x\n", rega, regb);
+	for (i = 0; i < 2; i++) {
+		orion_mdio_write(bus, 0, 0x12, regb);
+		orion_mdio_write(bus, 0, 0x16, 0x0);
+	}
+}
+
 static const struct of_device_id orion_mdio_match[] = {
 	{ .compatible = "marvell,orion-mdio" },
 	{ }
@@ -288,6 +347,7 @@
 static struct platform_driver orion_mdio_driver = {
 	.probe = orion_mdio_probe,
 	.remove = orion_mdio_remove,
+	.shutdown = orion_mdio_shutdown,
 	.driver = {
 		.name = "orion-mdio",
 		.of_match_table = orion_mdio_match,
