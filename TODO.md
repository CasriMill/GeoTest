## GeoTest: generování tisknutelných testů

### Podklady
- Použít existující mapu `czechia_hex_grid_final.svg` s hexagonální sítí; mapu znovu negenerovat.
- Použít existující JSON s objekty na území ČR.
- Zachovat stávající strukturu workspace a navázat na již vytvořený kód.
- Každá buňka sítě má označení písmenem; odpověď se zapisuje jako přiřazení objektu k písmenu buňky.

### Obsah testového listu
- Formát vhodný pro tisk na A4.
- Mapa s hexagonální sítí a označením buněk.
- Pod mapou tabulka se sloupci: hledaný objekt, přiřazení studenta, hodnocení hodnotitele.
- Dále malá tabulka se 2 řádky a 4 sloupci: Student, Predikce správná, Predikce nejitá, Predikce tipovaná nebo neurčená.
- Každý list označit identifikátorem sady testu.
- Připravit hodnotitelský list se správnými odpověďmi pro všech 5 variant dané úrovně obtížnosti.

### Počet a skladba objektů podle úrovně
1. **Úroveň 1 — 6 objektů:** 4 sídla s více než 100 000 obyvateli; 2 mezinárodní letiště.
2. **Úroveň 2 — 7 objektů:** 3 sídla s více než 100 000 obyvateli; 2 sídla s 50 000–100 000 obyvateli; 2 letiště mezinárodní nebo vojenská.
3. **Úroveň 3 — 8 objektů:** 1 sídlo s více než 100 000 obyvateli; 2 sídla s 50 000–100 000 obyvateli; 2 sídla s 10 000–50 000 obyvateli; 3 letiště mezinárodní nebo vojenská.
4. **Úroveň 4 — 9 objektů:** 2 sídla s 50 000–100 000 obyvateli; 4 sídla s 10 000–50 000 obyvateli; 3 letiště bez omezení kategorie.
5. **Úroveň 5 — 10 objektů:** 6 sídel s 5 000–75 000 obyvateli; 4 letiště bez omezení kategorie.

### Pravidlo pro shodu pozic
- V jednom testu může stejnou buňku sdílet sídlo a letiště.
- Na jedné pozici nesmějí být více než 2 objekty.

### Pravidlo pro velikost sídel
- je-li v zadání testu uveden interval velikosti populace sídla, platí do populace spodní hodnota intervalu a horní už ne

### Pravidlo pro opakování objektu v jedné úrovni testu
- v jedné úrovni obtížnosti testu se mohou objekty ve variantách opakovat, měla být shoda u n//2, kde "n" je počet objektů v dané obtížnosti

### K vyjasnění při implementaci
- Jak vytvořit 5 variant jedné úrovně a zda se objekty mezi variantami mohou opakovat.
- Zda se intervaly počtu obyvatel chápou včetně krajních hodnot.
- Význam označení „Predikce nejitá“ a přesný způsob bodování - jedná se jen o závěrečný odhad studenta.
- je-li zodpovězeno, odstranit z tohoto bloku