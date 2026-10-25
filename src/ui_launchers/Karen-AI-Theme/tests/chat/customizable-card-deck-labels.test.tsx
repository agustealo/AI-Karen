import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CustomizableCardDeck from '@/components/chat/CustomizableCardDeck';
import { Card, CardHeader, CardTitle } from '@/components/ui/card';

describe('customizable rail menu labels', () => {
  it('reads visible nested title text rather than substituting a generic card number', () => {
    render(
      <CustomizableCardDeck>
        <Card>
          <CardHeader>
            <CardTitle>
              <span>Runtime dispatch</span>
              <span>healthy</span>
            </CardTitle>
          </CardHeader>
        </Card>
      </CustomizableCardDeck>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Customize intelligence cards' }));
    expect(screen.getByText('Runtime dispatch healthy')).toBeTruthy();
    expect(screen.queryByText('Card 1')).toBeNull();
  });
});
