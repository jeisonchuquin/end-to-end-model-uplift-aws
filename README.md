# Piloto de Tarjeta Débito Física — Pipeline end-to-end

## Resumen ejecutivo

**¿Cómo le fue al piloto?** 

De 12,000 clientes activos en la base (tras limpieza), 5295 recibieron una tarjeta física, pero **solo el 47.8% la activó** (2529 de 5295), más de la mitad de las tarjetas entregadas nunca se usaron. Entre quienes sí activaron, el efecto es claro: comparando su propia actividad antes vs. después de activar la tarjeta, la **frecuencia mensual de transacciones subió +323% (0.88 → 3.71/mes)** y el **monto mensual subió +198% ($29 → $87/mes)**. 

El análisis Diff-in-Diff contra un grupo de control, clientes que nunca recibieron tarjeta física, misma ventana de tiempo confirma que el tratado sube **+3.58 transacciones/mes más que el control** en el mismo período (p < 0.001), es decir, el efecto no se explica por una tendencia general del negocio. La hipótesis del piloto se sostiene con evidencia estadística, el problema no es que la tarjeta física no funcione, es que la mitad de las tarjetas entregadas nunca llegan a probarse.

**¿A quién priorizar en la siguiente ola?** 

Antes incluso de recibir la tarjeta, los clientes que luego la activan ya muestran un patrón distinto, estadísticamente significativo pues Mann-Whitney p < 0.001, con 1.1 transacciones/mes vs. 0.9 para quienes se quedan solo con tarjeta virtual, y un gasto mensual de $36 vs. $29. Ese patrón pre-existente es predecible con datos que el banco ya tiene, sin necesidad de haber entregado la tarjeta primero. Si bien un modelo de propensión sería útil para responder si una persona utilizará o no su tarjeta física, como negocio se quiere priorizar también la ganacia, es decir se quiere identificar a las personas a las cuales entregarles una tarjeta física si cambie su comportamiento de consumo.

Por lo tanto se desarrolla el modelo uplift, se escoge esta metodología puesto que dado el contexto de negocio de que se tiene un presupuesto limitado para la siguiente ola, se quiere priorizar y encontrar a las personas que dado que les voy a dar una tarjeta física, cambie su comportamiento de consumo, es decir, se necesita identificar a clientes que necesiten un estímulo para que empiecen a consumir más y no se quiere gastar entregando tarjetas a quienes nunca cambiaran su comportamiento o a personas que de igual forma con o sin tarjeta seguiran aumentando su consumo e inclusive identificar a los clientes que por la insistencia de la contactabilidad deje de usarme.

De acuerdo con el modelo de uplift aplicado, se tiene la siguiente recomendación:

Tenemos que:

+ `persuadible`    : 2801 clientes (45.6%)
+ `seguros`     : 3261 clientes (53.0%)
+ `perdidos`     :    21 clientes (0.3%)
+ `perros dormidos`   :    65 clientes (1.1%)

1. **PRIORIZAR** "`persuadibles`" (2801 clientes, 45.6% de la siguiente ola candidata):
   
   Son los únicos donde la tarjeta física genera el cambio, el presupuesto limitado de tarjetas rinde más acá que en cualquier otro segmento. Esto es consistente con el ATE de +41.4%: la mayoría de ese efecto promedio viene de este grupo.

2. `Seguros` (3261 clientes, 53.0%): 
	
	Aumentarían su actividad con o sin tarjeta, si sobra presupuesto después de cubrir a los persuadibles, se les puede dar la tarjeta (no perjudica), pero no es donde más rinde.

3. `Perdidos` (21 clientes, 0.3%): 

	No vale la pena invertir tarjetas acá, ni con tarjeta cambiarían su comportamiento.

4. `Perros dormidos` (65 clientes, 1.1%): 

	Evitar darles la tarjeta, el modelo estima que podría reducir su actividad respecto a dejarlos solo con virtual (posible reacción negativa a más fricción/gasto en el canal físico).

