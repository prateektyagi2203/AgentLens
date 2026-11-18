export const metadata = { title: "Returns policy | Desi Threads (TEST STORE)" };

export default function ReturnsPolicy() {
  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="font-serif text-3xl font-bold">Returns policy</h1>
      <p>You can return most items within 15 days of delivery for a refund to your original payment method or store credit.</p>
      <ul className="list-disc space-y-1 pl-5 text-stone-700">
        <li>Items must be unworn, unwashed and carry original tags.</li>
        <li>Footwear must be returned in its original box.</li>
        <li>Accessories are eligible for exchange within 7 days.</li>
        <li>Refunds are processed within 5-7 working days of pickup.</li>
        <li>Free reverse pickup is available at most serviceable pincodes.</li>
      </ul>
      <p className="text-sm text-stone-500">This is a demo store: no real orders are placed and no refunds are issued.</p>
    </div>
  );
}
