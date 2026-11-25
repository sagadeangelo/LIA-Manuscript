# Costos de referencia y sensibilidad

Moneda base USD. Hoja de hipótesis al 25 de noviembre de 2026. Son presupuestos para evaluar capacidad y diferenciación, no cotizaciones, compromisos ni precios de venta. Supuesto ilustrativo de conversión 20 MXN/USD. En el ejemplo cada cliente paga una vez al mes y procesa un manuscrito de 80 mil palabras. El precio P de 199 MXN sirve solamente para calcular equilibrio. No incluye impuestos, soporte, personal editorial, contracargos, observabilidad de pago, transacciones adicionales o adquisición de clientes. Antes de fijar P, sustituir supuestos por una muestra de libros de demostración completos.

Para una API hipotética que cobre USD 1 por millón de tokens de entrada y USD 4 por millón de salida, con seis tokens de entrada y dos de salida por palabra contando contexto y revisión, el costo de IA es USD 0.000014 por palabra. No representa un proveedor contratado. Si se reintenta el 20% de la carga, multiplicar por 1.2. Para un motor propio, sustituir por horas de máquina × costo/hora y prorratear la capacidad ociosa. No sumar ambas alternativas como si operaran simultáneamente.

| Palabras | IA hipotética USD | Con 20% de reintentos | Ejemplo GPU USD 0.80/h a 1,000 palabras/h, sin tiempo ocioso |
|---:|---:|---:|---:|
| 10,000 | 0.14 | 0.168 | 8.00 |
| 50,000 | 0.70 | 0.84 | 40.00 |
| 80,000 | 1.12 | 1.344 | 64.00 |
| 120,000 | 1.68 | 2.016 | 96.00 |

Cómputo orientativo según tarifas de máquinas virtuales. El coste de R2 usa USD 0.015 por GB-mes desde el primer GB de forma conservadora, sin descontar franquicia ni sumar solicitudes. Se presupone que el volumen de solicitudes cabe en la franquicia. Se usa Stripe México con tarjeta nacional a 3.6% + 3 MXN, antes de IVA. Comisión por pago del ejemplo: 10.164 MXN, equivalente a USD 0.5082. Mercado Pago publica opciones de Checkout con componente variable según plazo y un componente fijo; comparar la modalidad y disponibilidad de fondos de la cuenta mexicana antes de decidir.

| Escenario | Clientes/mes | Cómputo y reserva de servicios/mes | Almacenamiento | Fijo USD/mes | IA/mes | Comisión/mes | Costo total/mes | Costo/cliente y libro | Equilibrio | Margen del escenario |
|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| A · piloto | 10 | 1 VM de 8 GiB, USD 48 | 10 GB | 48.15 | 11.20 | 5.08 | 64.43 | 6.44 | 6 clientes | 35.2% |
| B · crecimiento | 100 | 3 VM de USD 48 y USD 30 de reserva | 100 GB | 175.50 | 112.00 | 50.82 | 338.32 | 3.38 | 22 clientes | 66.0% |
| C · escala | 1000 | 10 VM de USD 84 y USD 200 de reserva | 1000 GB | 1055.00 | 1120.00 | 508.20 | 2683.20 | 2.68 | 127 clientes | 73.0% |

Equilibrio = redondear hacia arriba(fijo / (ingreso por usuario − procesamiento − comisión)). El costo por libro coincide con el costo por cliente únicamente bajo el supuesto de un libro mensual. Margen = (ingreso − costo modelado) / ingreso. B y C requieren pruebas de colas y capacidad; el número de máquinas es una hipótesis presupuestaria.

Fuentes: https://www.digitalocean.com/pricing/droplets · https://developers.cloudflare.com/r2/pricing/ · https://stripe.com/mx/pricing · https://www.mercadopago.com.mx/herramientas-para-vender/check-out
