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
- Vytvořit 5 variant každé úrovně; každá další varianta sdílí přesně `n // 2` objektů s předchozí variantou.

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
- Intervaly populace sídel mají spodní hranici včetně a horní hranici bez ní. Výslovné „více než 100 000“ znamená striktně nad 100 000.

- Pět variant se vytváří deterministicky podle seedu. Objekty se mohou opakovat mezi sousedními variantami v uvedeném rozsahu; ostatní objekty se losují mimo předchozí variantu.
- Závěrečná tabulka zachycuje studentovu predikci („správná“, „nejistá“, „tipovaná nebo neurčená“); nejde o automatické bodování.

### Další úkoly pro vylepšení
- [x] V učitelském přehledu doplnit sloupec „Obtížnost“.
- [ ] V učitelském přehledu do buňky "Obtížnost" doplnit vzdálenost pozice hledaného objektu na tomto řádku od středu příslušné buňky přepočtenou na % (bude-li objekt uprostřed buňky, bude mít hodnotu 0% a bude-li v rohu hexagonální buňky tak to bude 100%). Zatím je vytvořeno jen v difficult == 1, potřeba doplnit do ostatních difficult.
- [ ] V souhrnné přehledové mapě s hexagonáloní sítí v učitelském přehledu v každé difficulty zvlášť vyznačit body pozic hledaných objektů dané difficulty.
- [ ] V souhrnné přehledové mapě s hexagonáloní sítí v učitelském přehledu v každé difficulty zvlášť doplnit u bodů pozic hledaných objektů dané difficulty popiskama ve struktuře `X-Y/Y/Y/Y/Y` (kde X je difficulty a Y jsou čísla řádků pro verze 1–5, případně tečka, pokud objekt v dané verzi není). Popisek bude vpravo do vyznačeného bodu.