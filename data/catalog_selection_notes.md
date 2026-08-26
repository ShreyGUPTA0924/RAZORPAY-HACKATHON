# Catalog selection report

60 SKUs written to `data/catalog.json`.

Category: **Mobiles & Accessories** (phone cases/pouches, screen protectors, cables & chargers, headphones, power banks). The raw dataset has **no phone handset SKUs at all** in this category -- every row is an accessory, and phone compatibility is expressed as free text (title / description / a `Designed For`-style spec key), never as a link to an actual phone product.


## messy_parseable (40)

- `ACCEAZCVS4YGWUVH` Fuson Back Cover for Samsung Galaxy J7
- `ACCE8XZMFNFCDPXE` Kanu Book Cover for Spice Mi-720
- `ACCE8XZMZKPAJRGV` Kanu Book Cover for Huawei Honor X1
- `ACCE6CRF92JBR2HT` Instyles Back Cover for HTC One S
- `ACCEB79YTY3B8S9V` SNE Book Cover for Karbonn A37
- `ACCEJGYYMTQR4JXY` ACM Pouch for Swipe Elite Plus
- `ACCEJGYYYCGETMGA` ACM Pouch for Intex Aqua Lions 3g
- `ACCEA9K5ZCDNRGXN` Totta Pouch for Sony Xperia M5 Dual
- `ACCEF2R7ZWEDG674` Wise Guys Pouch for Lenovo S880
- `ACCEGH6TEZ8CAXEH` kits kart Pouch for Microsoft Lumia 1320
- `ACCEGH6RHZMYYWPQ` kits kart Pouch for OnePlus One
- `ACCEJWHTY2HVMG7Z` Newworld RTNE Pack Of One -583 Tempered Glass for Xiaomi Mi 4i
- `ACCEGRYUMK6MDDX2` Buynow Glass_54 Tempered Glass for Xiaomi Mi 4S
- `ACCEGRYU79JF2HZM` Buynow Glass_53 Tempered Glass for Lenovo K5 Note
- `ACCEGR4KPQS9XQWB` Protector G X1032 Tempered Glass for Motorola Moto G
- `ACCEGR4DQFCCXNH8` TRINK 6S Tempered Glass for APPLE IPHONE 6S
- `ACCEGQY59RFBNWE8` DEBOCK HTC desire 526 Tempered Glass for HTC desire 526
- `ACCEGQY5YJHWDCGW` DEBOCK Samsung Galaxy on5 Tempered Glass for Samsung Galaxy on5
- `ACCE4HJZJYY9TWVF` Scratchgard Original Armour Shield - N830 Screen Guard for Nokia Lumia 830
- `ACCEYSQ9ZP8B9ZE8` Gadgetshieldz 1358SPFB Screen Guard for Nokia Lumia 830
- `ACCE8ZY8JUNZHSHW` Nillkin 654 Tempered Glass for Samsung Galaxy S5 Mini
- `ACCDYHPHP4EHDHYC` Nillkin Z3-84345 Mirror Screen Guard for Blackberry Z3
- `ACCE5RZ9BK7EJK5P` ACM TEM1161 Tempered Glass for Huawei Honor 6
- `ACCEKFVVHCJHKVCR` Furst USB Adapter with Cable For Dzire VC Battery Charger
- `ACCEKFVWCGHSY6NF` Furst USB Adapter with Cable For Mt X (2nd Gen) Battery Charger
- `ACCEKFVWTGZXG5XK` Furst USB Adapter with Cable For Lnvo Vibe P1M Battery Charger
- `ACCEDTNRY73AGEHF` D'clair Micromax A46 Battery Charger
- `ACCEDTNRXHXZKH4G` D'clair Huwai Honor 4X Battery Charger
- `ACCEGYP2TMX2NUPH` XEBAC XEBAC-ADAPTER-B1017 Battery Charger
- `ACCEGKFEZFBG3DZW` Generix OTG for Xiaomi Mi4 OTG Cable
- `ACCEGKFHWYVFNCX5` Generix OTG for Blackberry Priv OTG Cable
- `ACCEGKTSGJEEVTZ4` AW High Speed Charge and Sync Usb for Iphone 6 Lightning Cable
- `ACCEEEWGHE9JGKQE` Acromax Type C for One Plus Two USB C Type Cable
- `ACCEGYCGPDMC5UFF` XEBAC For Alcatel One Touch Idol X+ USB Cable
- `ACCEGK9TXV3RMMXY` SYL WALL CHARGER/TRAVEL CHARGER/FAST CHARGER/PORTABLE CHARGER FOR LETV 1S Battery Charger
- `ACCEHZF9EDRGHXCF` DEBOCK DEBOCK Earphone For Samsung galaxy s advance i9070 Stereo Dynamic Headphone Wired Headphones
- `ACCEGKDGVZWHYV5H` CONVENIENCE vm46 headphone for XIOMI Mi4 and Mi4i Signature vm46 Stereo Wired Headphones
- `ACCEGKN7FAWUGRJR` Dhhan Earphones/Handfree for Iphone 4/4s/4g/5/5c/5s Stereo Dynamic Headphone Wired Bluetooth Headphones
- `PWBEGH7TYBFEEZQK` Wayona 10000mAh Wireless 10000mAh Power bank With Dual USB Output 10000 mAh
- `PWBEHD23J2HXNMBT` Zebie SPB100096 Solar 12000 MAH Power Bank 12000 mAh

## missing_ambiguous (15)

- `ACCEGNYUMARHZWGW` snjmart Gold Note 4 Stereo Dynamic Earphone Wired Headphones
  - why: designed_for='All Smart Phones' (generic); 'Note 4' in the title could be a phone model or just the product's own name
- `ACCEGPC9DA8TGRYY` snjmart M5 Dual Stereo Dynamic Earphone Wired Headphones
  - why: designed_for='All Smart Phones'; 'M5' in title is not attributable to a specific phone
- `ACCEGZ5PGHCDZTNY` RJ philips Earphone 23000 Stereo Dynamic Headphone Wired Headphones
  - why: designed_for='Mobile'; '23000' in title is a model number, not a phone reference
- `ACCEGZ8GRVUADQ4Y` LIFE LIKE S450 3.0 WITH MIC GOOD SOUND QUALITY Wired & Wireless Bluetooth Headphones
  - why: title says 'Wired & Wireless Bluetooth' in the same breath -- contradicts itself on the single most basic attribute
- `ACCEGZ8GDQKDXMTT` LIFE LIKE STN-840 4.1 WITH MIC Wireless Bluetooth Headset
  - why: designed_for='Mobile'; no specific phone named anywhere
- `ACCEGPBYNU6BPFNR` snjmart C5 Ultra Dual Stereo Dynamic Earphone Wired Headphones
  - why: designed_for='All Smart Phones'; 'C5' is ambiguous (own product line vs a phone model)
- `ACCEGKXQ2AQQ2AQV` Lexel High Quality Braided Metal Head Pure Copper Fast Charging 1.5 Meter Long for Iphone & Ipad Lightning Cable
  - why: compat stated as 'for All Smartphone like Samsung HTC etc' -- explicitly open-ended, not enumerable
- `ACCEGKFG5VWCR3JG` Generix Android Smart Phone OTG OTG Cable
  - why: designed_for='Mobile, Tablet'; title only says 'Android Smart Phone', no model
- `ACCDSWHWFDAK95ZT` Dicapac Grip Back Cover for Galaxy Note
  - why: designed_for='Galaxy Note' with no number -- Note, Note 2, Note 3, Note 4, Note 5 all fit that string
- `ACCED9RVHZNWFMB4` Vps Flip Cover for 7 Inch Oppo Find 7A
  - why: title says '7 Inch Oppo Find 7A', but the Find 7A is a ~5.5in phone -- the size claim contradicts the named device
- `ACCDKYS6Y5NY9SZW` Samsung Pouch for Samsung Galaxy Note 510
  - why: 'Samsung Galaxy Note 510' does not match any real Samsung Note model number
- `PWBEGG7AMQ6UGNZW` codio World A114 Sony CP-V0 112 10000 mAh
  - why: brand is 'codio World' but the model name is 'Sony CP-V0 112' -- unclear if this is a genuine Sony part or an unrelated seller's own naming
- `CGPEGQYHCJABVGHZ` Newdort Usb Charger Full Charging Pad
  - why: compat given only as 'Motorola' (brand-level), no model at all
- `ACCEDTNRVGAGRCWF` D'clair Micromax Canvas Play 4G Q469 Battery Charger
  - why: no wattage/amperage anywhere in specs or prose -- only 'Dual USB Compatible Compact Durable'
- `ACCEGKXQ9ZFSWKMU` Lexel High Quality Braided Metal Head Pure Copper Fast Charging 1.5 Meter Long for All Smartphone like Samsung HTC etc USB Cable
  - why: same open-ended 'All Smartphone like Samsung HTC etc' compat framing as its sibling SKU above

## unparseable (5)

- `ACCEGKFGE9EGBSBZ` Generix OTG for Sony Xperia M5 OTG Cable
  - why: empty product_specifications; description is pure Flipkart boilerplate with no attributes beyond the title
- `ACCEEV5VVP97HRTR` Sound Logic Soundlogic Dynabass Foldable Headphones Headphones
  - why: only Brand/Model ID/Color present; no wired-vs-wireless, no connector, no phone compatibility anywhere
- `ACCEEV5VN3XFH8CH` Dynex Digital Full Size Headphone Dx-Hp550 Headphones
  - why: only Brand/Model ID/Color present; same gap as above
- `ACCEEV5V5VD5DR9C` Radius Earbuds Radheadphones Hp-Rhf41P Headphones
  - why: only Brand/Model ID/Color present; same gap as above
- `ACCEEV5V5ERYC6RN` Naxa Electronics Naxa Ne-929 Wh Headphones () Headphones
  - why: only Brand/Model ID/Color present; title even has a stray empty '()' artifact from the scrape
